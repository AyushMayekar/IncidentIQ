"""Evidence processing: queue, claim, parse, persist.

Design notes
------------
* One worker process is supported (see :mod:`incidentiq.worker` and the
  ``worker_lease`` table). The global/per-type limits below are therefore
  globally effective; they are *not* advertised as cross-process limits.
* Claiming happens in one transaction with ``FOR UPDATE SKIP LOCKED`` on
  PostgreSQL. SQLite (tests) is single-writer, so a plain select/update in one
  transaction is equivalent there.
* Parsed rows and the ``parsed`` transition share one transaction: a crash can
  never expose a partially written result.
* Only a *completed* run with a matching content hash, parser version and row
  count may skip parsing. Failed or interrupted jobs never qualify.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import Session

from incidentiq.config import Settings, get_settings
from incidentiq.models import (
    EvidenceJob,
    EvidenceSource,
    ParsedEvidenceRecord,
)
from incidentiq.parsers import require_parser

logger = logging.getLogger("incidentiq.processing")

PROCESSING_STATUSES = (
    "queued",
    "validating",
    "extracting",
    "parsing",
    "normalizing",
    "parsed",
    "failed",
)
ACTIVE_STATUSES = ("validating", "extracting", "parsing", "normalizing")
TERMINAL_STATUSES = ("parsed", "failed")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_job(
    db: Session, evidence: EvidenceSource, settings: Settings | None = None
) -> EvidenceJob:
    """Create the durable job for a just-uploaded evidence row.

    The caller commits evidence + job together, which is what makes uploads
    atomic.
    """
    settings = settings or get_settings()
    now = utcnow()
    job = EvidenceJob(
        id=uuid4(),
        evidence_id=evidence.id,
        incident_id=evidence.incident_id,
        evidence_type=evidence.evidence_type or "",
        status="queued",
        attempts=0,
        max_attempts=settings.worker_max_attempts,
        records_parsed=0,
        created_at=now,
        updated_at=now,
    )
    evidence.parse_status = "queued"
    db.add(job)
    return job


def claim_jobs(
    db: Session,
    settings: Settings | None = None,
    limit: int | None = None,
) -> list[UUID]:
    """Atomically claim up to the configured limits. Returns claimed job IDs."""
    settings = settings or get_settings()
    batch = limit or settings.worker_batch_size

    statement = (
        select(EvidenceJob)
        .where(EvidenceJob.status == "queued")
        .order_by(EvidenceJob.created_at.asc(), EvidenceJob.id.asc())
        .limit(batch)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)

    candidates = list(db.scalars(statement).all())
    if not candidates:
        return []

    active_rows = db.execute(
        select(EvidenceJob.evidence_type, func.count())
        .where(EvidenceJob.status.in_(ACTIVE_STATUSES))
        .group_by(EvidenceJob.evidence_type)
    ).all()
    per_type = {evidence_type: count for evidence_type, count in active_rows}
    active_total = sum(per_type.values())

    now = utcnow()
    claimed: list[UUID] = []
    for job in candidates:
        if active_total >= settings.worker_max_files_global:
            break
        if per_type.get(job.evidence_type, 0) >= settings.worker_max_files_per_type:
            continue

        job.status = "validating"
        job.attempts += 1
        job.claimed_at = now
        job.heartbeat_at = now
        job.started_at = job.started_at or now
        job.updated_at = now
        evidence = db.get(EvidenceSource, job.evidence_id)
        if evidence is not None:
            evidence.parse_status = "validating"

        per_type[job.evidence_type] = per_type.get(job.evidence_type, 0) + 1
        active_total += 1
        claimed.append(job.id)

    db.commit()
    return claimed


def _stage(
    db: Session, job: EvidenceJob, evidence: EvidenceSource | None, status: str
) -> None:
    now = utcnow()
    job.status = status
    job.heartbeat_at = now
    job.updated_at = now
    if evidence is not None:
        evidence.parse_status = status
    db.commit()
    db.refresh(job)


def _record_count(db: Session, evidence_id: UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(ParsedEvidenceRecord)
            .where(ParsedEvidenceRecord.evidence_id == evidence_id)
        )
        or 0
    )


def _finish(
    db: Session,
    job: EvidenceJob,
    evidence: EvidenceSource,
    *,
    records: list,
    duration_ms: int,
    parser_version: str,
    batch_size: int,
) -> None:
    """Replace derived rows and mark the job parsed in one transaction."""
    db.execute(
        delete(ParsedEvidenceRecord).where(
            ParsedEvidenceRecord.evidence_id == evidence.id
        )
    )

    rows: list[dict] = []
    now = utcnow()
    for record in records:
        rows.append(
            {
                "id": uuid4(),
                "record_id": record.record_id,
                "incident_id": evidence.incident_id,
                "evidence_id": evidence.id,
                "evidence_type": record.evidence_type,
                "record_type": record.record_type,
                "record_index": record.source.record_index,
                "content": record.content,
                "timestamp_start": record.timestamp_start,
                "timestamp_end": record.timestamp_end,
                "attributes": record.attributes,
                "source": record.source.model_dump(),
                "parser_name": record.parser_name,
                "parser_version": record.parser_version,
                "created_at": now,
            }
        )

    chunk_size = max(1, batch_size)
    for start in range(0, len(rows), chunk_size):
        db.execute(insert(ParsedEvidenceRecord), rows[start : start + chunk_size])

    job.status = "parsed"
    job.records_parsed = len(rows)
    job.processing_duration_ms = duration_ms
    job.completed_at = now
    job.completed_content_hash = evidence.content_hash
    job.completed_parser_version = parser_version
    job.heartbeat_at = now
    job.updated_at = now
    job.error_code = None
    job.error_message = None
    evidence.parse_status = "parsed"
    db.commit()
    db.refresh(job)


def _fail(
    db: Session, job_id: UUID, code: str, message: str
) -> None:
    """Record a safe, human-readable failure. Stack traces never reach the API."""
    job = db.get(EvidenceJob, job_id)
    if job is None:
        return
    evidence = db.get(EvidenceSource, job.evidence_id)
    now = utcnow()
    job.status = "failed"
    job.error_code = code
    job.error_message = message[:1000]
    job.completed_at = now
    job.heartbeat_at = now
    job.updated_at = now
    # A failed run can never satisfy the skip signature, and any rows from an
    # earlier attempt must not masquerade as the result of this attempt.
    job.completed_content_hash = None
    job.completed_parser_version = None
    job.records_parsed = 0
    db.execute(
        delete(ParsedEvidenceRecord).where(
            ParsedEvidenceRecord.evidence_id == job.evidence_id
        )
    )
    if evidence is not None:
        evidence.parse_status = "failed"
    db.commit()
    logger.warning(
        "evidence processing failed",
        extra={
            "evidence_id": str(job.evidence_id),
            "incident_id": str(job.incident_id),
            "evidence_type": job.evidence_type,
            "attempt": job.attempts,
            "error_code": code,
        },
    )


def _can_skip(
    db: Session,
    job: EvidenceJob,
    evidence: EvidenceSource,
    version: str,
    settings: Settings,
) -> bool:
    """A verified, completed result is the *only* thing that may skip parsing."""
    if not settings.parser_skip_unchanged:
        return False
    return (
        job.completed_at is not None
        and job.error_code is None
        and job.completed_content_hash == evidence.content_hash
        and job.completed_parser_version == version
        and job.records_parsed == _record_count(db, evidence.id)
    )


def run_job(db: Session, job_id: UUID, settings: Settings | None = None) -> None:
    """Process one claimed job. Safe to call again; work is idempotent."""
    settings = settings or get_settings()
    job = db.get(EvidenceJob, job_id)
    if job is None or job.status != "validating":
        return

    evidence = db.get(EvidenceSource, job.evidence_id)
    if evidence is None:
        _fail(db, job_id, "evidence_missing", "The evidence file no longer exists.")
        return

    started = perf_counter()
    try:
        parser = require_parser(job.evidence_type)

        _stage(db, job, evidence, "extracting")
        text = evidence.raw_content or ""
        if not text.strip():
            _finish(
                db,
                job,
                evidence,
                records=[],
                duration_ms=0,
                parser_version=parser.version,
                batch_size=settings.parser_batch_size,
            )
            logger.info(
                "evidence processing skipped empty content",
                extra={"evidence_id": str(evidence.id)},
            )
            return

        if _can_skip(db, job, evidence, parser.version, settings):
            duration_ms = int((perf_counter() - started) * 1000)
            job.processing_duration_ms = duration_ms
            job.completed_at = utcnow()
            job.heartbeat_at = job.completed_at
            job.status = "parsed"
            evidence.parse_status = "parsed"
            db.commit()
            logger.info(
                "evidence processing skipped unchanged result",
                extra={
                    "evidence_id": str(evidence.id),
                    "records": job.records_parsed,
                    "duration_ms": duration_ms,
                },
            )
            return

        _stage(db, job, evidence, "parsing")
        result = parser.parse(text, evidence.source_name)
        records = result.records

        if len(records) > settings.parser_max_records:
            records = records[: settings.parser_max_records]
            logger.warning(
                "parser record cap reached",
                extra={
                    "evidence_id": str(evidence.id),
                    "cap": settings.parser_max_records,
                },
            )

        _stage(db, job, evidence, "normalizing")
        duration_ms = int((perf_counter() - started) * 1000)
        _finish(
            db,
            job,
            evidence,
            records=records,
            duration_ms=duration_ms,
            parser_version=parser.version,
            batch_size=settings.parser_batch_size,
        )

        logger.info(
            "evidence processed",
            extra={
                "evidence_id": str(evidence.id),
                "incident_id": str(evidence.incident_id),
                "evidence_type": job.evidence_type,
                "bytes": evidence.byte_size,
                "records": len(records),
                "duration_ms": duration_ms,
                "records_per_second": round(
                    len(records) / (duration_ms / 1000), 2
                )
                if duration_ms > 0
                else None,
                "parser_warnings": len(result.warnings),
                "executor": settings.parser_executor,
                "attempt": job.attempts,
            },
        )
    except KeyError:
        db.rollback()
        _fail(
            db,
            job_id,
            "unsupported_type",
            "No parser is available for this evidence type.",
        )
    except Exception:  # noqa: BLE001 - isolate one file's failure from the batch
        db.rollback()
        logger.exception(
            "unexpected evidence processing error",
            extra={"evidence_id": str(job.evidence_id), "job_id": str(job_id)},
        )
        _fail(
            db,
            job_id,
            "processing_error",
            "Evidence could not be processed. Retry the file or check its contents.",
        )


def recover_stale_jobs(
    db: Session, settings: Settings | None = None
) -> list[UUID]:
    """Requeue jobs whose worker stopped heartbeating, or fail them out."""
    settings = settings or get_settings()
    cutoff = utcnow() - timedelta(seconds=settings.worker_stale_after_seconds)
    statement = select(EvidenceJob).where(
        EvidenceJob.status.in_(ACTIVE_STATUSES),
        or_(
            EvidenceJob.heartbeat_at < cutoff,
            (
                EvidenceJob.heartbeat_at.is_(None)
                & (EvidenceJob.claimed_at < cutoff)
            ),
        ),
    )
    stale = list(db.scalars(statement).all())
    recovered: list[UUID] = []
    for job in stale:
        evidence = db.get(EvidenceSource, job.evidence_id)
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.error_code = "stale_timeout"
            job.error_message = (
                "Processing stopped unexpectedly and could not be recovered."
            )
            job.completed_at = utcnow()
            if evidence is not None:
                evidence.parse_status = "failed"
            logger.warning(
                "stale job exhausted retries",
                extra={"job_id": str(job.id), "attempts": job.attempts},
            )
        else:
            job.status = "queued"
            job.claimed_at = None
            job.heartbeat_at = None
            if evidence is not None:
                evidence.parse_status = "queued"
            recovered.append(job.id)
        job.updated_at = utcnow()
    db.commit()
    return recovered


def retry_job(db: Session, evidence: EvidenceSource) -> EvidenceJob | None:
    """Idempotently requeue a failed (or legacy) evidence file.

    Locking the job row serialises retry against claiming and deletion.
    """
    statement = (
        select(EvidenceJob)
        .where(EvidenceJob.evidence_id == evidence.id)
        .with_for_update()
    )
    if db.bind is not None and db.bind.dialect.name != "postgresql":
        statement = select(EvidenceJob).where(EvidenceJob.evidence_id == evidence.id)
    job = db.scalar(statement)
    if job is None:
        if not evidence.evidence_type:
            return None
        job = enqueue_job(db, evidence)
        db.commit()
        db.refresh(job)
        return job

    if job.status in ACTIVE_STATUSES or job.status == "queued":
        return job  # already in flight: retry is idempotent
    if job.status == "parsed":
        return None  # nothing to retry; caller answers 409

    job.status = "queued"
    job.attempts = 0
    job.error_code = None
    job.error_message = None
    job.claimed_at = None
    job.heartbeat_at = None
    job.completed_at = None
    job.completed_content_hash = None
    job.completed_parser_version = None
    job.updated_at = utcnow()
    evidence.parse_status = "queued"
    db.commit()
    db.refresh(job)
    return job
