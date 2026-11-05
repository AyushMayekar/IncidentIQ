"""Processing pipeline, job lifecycle, concurrency, cascade and retry tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import Session

from incidentiq.config import get_settings
from incidentiq.models import (
    EvidenceJob,
    EvidenceSource,
    Incident,
    ParsedEvidenceRecord,
)
from incidentiq.services import (
    claim_jobs,
    recover_stale_jobs,
    run_job,
)


def make_incident(client: TestClient, title: str = "Checkout failures") -> str:
    response = client.post(
        "/api/v1/incidents",
        json={
            "title": title,
            "description": "p99 latency above threshold",
            "service": "checkout-api",
            "severity": "high",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def upload(
    client: TestClient,
    incident_id: str,
    content: bytes = b"2026-11-03T09:14:05Z ERROR [checkout-api] timed out\n",
    filename: str = "app.log",
    evidence_type: str = "application_log",
) -> dict:
    response = client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        files={"file": (filename, content)},
        data={"evidence_type": evidence_type},
    )
    assert response.status_code == 201, response.text
    return response.json()


def uid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(value)


def job_for(db: Session, evidence_id: str | UUID) -> EvidenceJob | None:
    return db.scalar(
        select(EvidenceJob).where(EvidenceJob.evidence_id == uid(evidence_id))
    )


def process_next(db: Session) -> None:
    claimed = claim_jobs(db, limit=1)
    assert claimed, "expected a claimable job"
    run_job(db, claimed[0])


def test_upload_creates_a_queued_job_atomically(client: TestClient, db_session: Session) -> None:
    incident_id = make_incident(client)
    body = upload(client, incident_id)

    job = job_for(db_session, body["id"])
    assert job is not None
    assert job.status == "queued"
    assert str(job.incident_id) == body["incident_id"]
    assert job.evidence_type == "application_log"
    assert job.attempts == 0

    evidence = db_session.get(EvidenceSource, uid(body["id"]))
    assert evidence is not None
    assert evidence.parse_status == "queued"


def test_job_lifecycle_persists_records_with_provenance(
    client: TestClient, db_session: Session
) -> None:
    incident_id = make_incident(client)
    body = upload(client, incident_id)

    process_next(db_session)

    job = job_for(db_session, body["id"])
    assert job is not None
    assert job.status == "parsed"
    assert job.records_parsed == 1
    assert job.completed_at is not None
    assert job.completed_content_hash == body["content_hash"]
    assert job.completed_parser_version == "1"
    assert job.processing_duration_ms is not None
    assert job.error_message is None

    evidence = db_session.get(EvidenceSource, uid(body["id"]))
    assert evidence is not None
    assert evidence.parse_status == "parsed"

    record = db_session.scalar(
        select(ParsedEvidenceRecord).where(
            ParsedEvidenceRecord.evidence_id == uid(body["id"])
        )
    )
    assert record is not None
    assert str(record.incident_id) == incident_id
    assert str(record.evidence_id) == body["id"]
    assert record.record_type == "log_event"
    assert record.content == "timed out"
    assert record.source["filename"] == "app.log"
    assert record.source["start_line"] == 1
    assert record.source["record_index"] == 0
    assert record.parser_name == "application_log"
    assert record.parser_version == "1"

    listed = client.get(f"/api/v1/incidents/{incident_id}/evidence").json()[0]
    assert listed["parse_status"] == "parsed"
    assert listed["record_count"] == 1
    assert listed["processed_at"] is not None


def test_processing_failure_is_isolated_and_retry_is_idempotent(
    client: TestClient, db_session: Session
) -> None:
    incident_id = make_incident(client)
    body = upload(client, incident_id)

    job = job_for(db_session, body["id"])
    assert job is not None
    job.evidence_type = "not_a_real_type"
    db_session.commit()

    claimed = claim_jobs(db_session, limit=1)
    assert claimed
    run_job(db_session, claimed[0])

    job = job_for(db_session, body["id"])
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "unsupported_type"
    assert "Traceback" not in (job.error_message or "")
    assert db_session.get(EvidenceSource, uid(body["id"])).parse_status == "failed"

    first = client.post(f"/api/v1/incidents/{incident_id}/evidence/{body['id']}/retry")
    second = client.post(f"/api/v1/incidents/{incident_id}/evidence/{body['id']}/retry")
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["parse_status"] == "queued"
    assert second.json()["parse_status"] == "queued"
    assert job_for(db_session, body["id"]).attempts == 0

    job = job_for(db_session, body["id"])
    job.evidence_type = "application_log"
    db_session.commit()
    process_next(db_session)
    assert job_for(db_session, body["id"]).status == "parsed"

    # A parsed file cannot be retried.
    response = client.post(f"/api/v1/incidents/{incident_id}/evidence/{body['id']}/retry")
    assert response.status_code == 409


def test_skip_unchanged_only_uses_a_verified_completed_result(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = make_incident(client)
    body = upload(client, incident_id)
    process_next(db_session)
    job = job_for(db_session, body["id"])
    assert job is not None and job.status == "parsed"

    # Re-run a completed job with a matching signature: parsing is skipped,
    # which we prove by making the parser explode.
    from incidentiq.parsers import require_parser

    parser = require_parser("application_log")

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("parser must not run when the result is verified")

    monkeypatch.setattr(type(parser), "parse", explode)
    job.status = "validating"
    job.attempts += 1
    db_session.commit()
    run_job(db_session, job.id)
    assert job_for(db_session, body["id"]).status == "parsed"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ParsedEvidenceRecord)
            .where(ParsedEvidenceRecord.evidence_id == uid(body["id"]))
        )
        == 1
    )

    # A version bump invalidates the signature and forces a real re-parse.
    monkeypatch.undo()
    job = job_for(db_session, body["id"])
    job.status = "validating"
    job.completed_parser_version = "0"
    db_session.commit()
    calls = {"n": 0}
    original = type(require_parser("application_log")).parse

    def counting(self: object, text: str, filename: str):
        calls["n"] += 1
        return original(self, text, filename)

    monkeypatch.setattr(type(require_parser("application_log")), "parse", counting)
    run_job(db_session, job.id)
    assert calls["n"] == 1

    # Missing parsed rows also invalidate the signature.
    monkeypatch.undo()
    db_session.execute(
        text("DELETE FROM parsed_evidence_records WHERE evidence_id = :id"),
        {"id": body["id"].replace("-", "")},
    )
    db_session.commit()
    job = job_for(db_session, body["id"])
    job.status = "validating"
    job.completed_parser_version = "1"
    db_session.commit()
    calls["n"] = 0
    monkeypatch.setattr(type(require_parser("application_log")), "parse", counting)
    run_job(db_session, job.id)
    assert calls["n"] == 1


def test_failed_jobs_are_never_treated_as_processed(
    client: TestClient, db_session: Session
) -> None:
    incident_id = make_incident(client)
    body = upload(client, incident_id)
    job = job_for(db_session, body["id"])
    assert job is not None

    job.status = "validating"
    job.attempts = 1
    job.completed_at = datetime.now(timezone.utc)
    job.completed_content_hash = body["content_hash"]
    job.completed_parser_version = "1"
    job.records_parsed = 0
    job.error_code = "processing_error"
    db_session.commit()

    # Even with a completed-looking signature, a failed job must re-parse.
    job = job_for(db_session, body["id"])
    job.status = "failed"
    db_session.commit()
    db_session.execute(
        update(EvidenceJob)
        .where(EvidenceJob.id == job.id)
        .values(status="validating")
    )
    db_session.commit()
    run_job(db_session, job.id)
    assert job_for(db_session, body["id"]).status == "parsed"


def test_batch_inserts_are_chunked(
    client: TestClient, db_session: Session
) -> None:
    rows = 1201
    content = "\n".join(
        f"2026-11-03T09:14:05Z INFO [checkout-api] event {number}"
        for number in range(rows)
    ).encode()
    incident_id = make_incident(client)
    body = upload(client, incident_id, content=content, filename="bulk.log")

    inserts: list[str] = []

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(
            "INSERT INTO PARSED_EVIDENCE_RECORDS"
        ):
            inserts.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", before_execute)
    try:
        process_next(db_session)
    finally:
        event.remove(bind, "before_cursor_execute", before_execute)

    job = job_for(db_session, body["id"])
    assert job is not None and job.records_parsed == rows
    assert 1 <= len(inserts) <= 3  # 1201 rows at 500 per executemany


def test_global_and_per_type_limits(client: TestClient, db_session: Session) -> None:
    settings = get_settings()
    incident_id = make_incident(client)
    for number in range(4):
        upload(
            client,
            incident_id,
            content=f"2026-11-03T09:14:05Z INFO [checkout-api] a{number}\n".encode(),
            filename=f"a{number}.log",
        )
    upload(
        client,
        incident_id,
        content=b"2026-11-03T09:14:05Z INFO [checkout-api] m1\n",
        filename="m1.txt",
        evidence_type="metrics",
    )

    claimed = claim_jobs(db_session, settings=settings, limit=10)
    # One application_log (per-type limit) and one metrics (different type),
    # below the global cap of three.
    assert len(claimed) == 2
    types = [
        db_session.get(EvidenceJob, job_id).evidence_type for job_id in claimed
    ]
    assert sorted(types) == ["application_log", "metrics"]

    # Finish the claimed jobs; the next same-type job can then be claimed.
    for job_id in claimed:
        job = db_session.get(EvidenceJob, job_id)
        job.status = "parsed"
    db_session.commit()
    again = claim_jobs(db_session, settings=settings, limit=10)
    assert len(again) == 1
    assert db_session.get(EvidenceJob, again[0]).evidence_type == "application_log"


def test_stale_jobs_recover_or_fail_after_bounded_attempts(
    client: TestClient, db_session: Session
) -> None:
    incident_id = make_incident(client)
    first = upload(client, incident_id, content=b"first\n", filename="first.txt")
    second = upload(client, incident_id, content=b"second\n", filename="second.txt")
    settings = get_settings()
    old = datetime.now(timezone.utc) - timedelta(
        seconds=settings.worker_stale_after_seconds + 60
    )

    job = job_for(db_session, first["id"])
    job.status = "parsing"
    job.attempts = 1
    job.heartbeat_at = old
    db_session.commit()

    recovered = recover_stale_jobs(db_session, settings)
    assert recovered == [job.id]
    assert job_for(db_session, first["id"]).status == "queued"

    job = job_for(db_session, second["id"])
    job.status = "parsing"
    job.attempts = job.max_attempts
    job.heartbeat_at = old
    db_session.commit()
    recover_stale_jobs(db_session, settings)
    failed = job_for(db_session, second["id"])
    assert failed.status == "failed"
    assert failed.error_code == "stale_timeout"
    assert db_session.get(EvidenceSource, uid(second["id"])).parse_status == "failed"


def test_delete_evidence_removes_job_and_records(
    client: TestClient, db_session: Session
) -> None:
    incident_id = make_incident(client)
    body = upload(client, incident_id)
    process_next(db_session)

    response = client.delete(
        f"/api/v1/incidents/{incident_id}/evidence/{body['id']}"
    )
    assert response.status_code == 204
    assert db_session.get(EvidenceSource, uid(body["id"])) is None
    assert job_for(db_session, body["id"]) is None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ParsedEvidenceRecord)
            .where(ParsedEvidenceRecord.evidence_id == uid(body["id"]))
        )
        == 0
    )


def test_delete_is_refused_while_evidence_is_processing(
    client: TestClient, db_session: Session
) -> None:
    incident_id = make_incident(client)
    body = upload(client, incident_id)
    claimed = claim_jobs(db_session, limit=1)
    assert claimed

    response = client.delete(
        f"/api/v1/incidents/{incident_id}/evidence/{body['id']}"
    )
    assert response.status_code == 409
    assert db_session.get(EvidenceSource, uid(body["id"])) is not None


def test_retry_unknown_evidence_returns_404(client: TestClient) -> None:
    incident_id = make_incident(client)
    response = client.post(
        f"/api/v1/incidents/{incident_id}/evidence/{uuid4()}/retry"
    )
    assert response.status_code == 404


def test_database_cascade_from_incident_to_all_derived_rows(
    client: TestClient, db_session: Session
) -> None:
    incident_id = make_incident(client)
    body = upload(client, incident_id)
    process_next(db_session)

    # Bypass the ORM entirely: the database itself must cascade.
    db_session.execute(
        text("DELETE FROM incidents WHERE id = :id"),
        {"id": incident_id.replace("-", "")},
    )
    db_session.commit()

    for model in (EvidenceSource, EvidenceJob, ParsedEvidenceRecord):
        assert (
            db_session.scalar(select(func.count()).select_from(model)) == 0
        ), f"{model.__tablename__} left orphan rows"


def test_parsed_records_are_isolated_between_incidents(
    client: TestClient, db_session: Session
) -> None:
    first_incident = make_incident(client, "First")
    second_incident = make_incident(client, "Second")
    first = upload(client, first_incident, content=b"first only\n", filename="first.txt")
    second = upload(
        client, second_incident, content=b"second only\n", filename="second.txt"
    )

    process_next(db_session)
    process_next(db_session)

    for body, incident_id in ((first, first_incident), (second, second_incident)):
        records = db_session.scalars(
            select(ParsedEvidenceRecord).where(
                ParsedEvidenceRecord.evidence_id == uid(body["id"])
            )
        ).all()
        assert records
        assert {str(record.incident_id) for record in records} == {incident_id}

    client.delete(f"/api/v1/incidents/{first_incident}/evidence/{first['id']}")
    remaining = db_session.scalars(select(ParsedEvidenceRecord)).all()
    assert remaining
    assert {str(record.evidence_id) for record in remaining} == {second["id"]}
