"""Database-backed single-worker lease.

Only one worker process may run against a database. The lease is a singleton
row so the same code path is exercised by PostgreSQL and by the SQLite tests.
If a second worker starts while the first holds a live lease it exits; that is
what makes the in-process global/per-type concurrency limits effective.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from incidentiq.config import Settings, get_settings
from incidentiq.models import WorkerLease


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_row(db: Session) -> None:
    if db.get(WorkerLease, 1) is not None:
        return
    db.add(WorkerLease(id=1))
    try:
        db.commit()
    except IntegrityError:
        # Another worker created it first; that is fine.
        db.rollback()


def acquire_lease(
    db: Session, owner: str, settings: Settings | None = None
) -> bool:
    """Take the singleton lease when it is free or expired."""
    settings = settings or get_settings()
    _ensure_row(db)
    now = _now()
    expires = now + timedelta(seconds=settings.worker_lease_seconds)
    result = db.execute(
        update(WorkerLease)
        .where(
            WorkerLease.id == 1,
            or_(WorkerLease.expires_at.is_(None), WorkerLease.expires_at < now),
        )
        .values(
            owner=owner,
            acquired_at=now,
            heartbeat_at=now,
            expires_at=expires,
        )
    )
    db.commit()
    return (result.rowcount or 0) == 1


def renew_lease(
    db: Session, owner: str, settings: Settings | None = None
) -> bool:
    settings = settings or get_settings()
    now = _now()
    result = db.execute(
        update(WorkerLease)
        .where(WorkerLease.id == 1, WorkerLease.owner == owner)
        .values(
            heartbeat_at=now,
            expires_at=now + timedelta(seconds=settings.worker_lease_seconds),
        )
    )
    db.commit()
    return (result.rowcount or 0) == 1


def release_lease(db: Session, owner: str) -> None:
    now = _now()
    db.execute(
        update(WorkerLease)
        .where(WorkerLease.id == 1, WorkerLease.owner == owner)
        .values(owner=None, expires_at=now, heartbeat_at=now)
    )
    db.commit()


def lease_owner(db: Session) -> str | None:
    lease = db.scalar(select(WorkerLease).where(WorkerLease.id == 1))
    return lease.owner if lease is not None else None
