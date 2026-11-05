"""Single-worker lease, claiming safety and cascade/FK enforcement tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from incidentiq.config import get_settings
from incidentiq.models import WorkerLease
from incidentiq.services import acquire_lease, release_lease, renew_lease


def test_only_one_worker_can_hold_the_lease(db_session: Session) -> None:
    settings = get_settings()
    assert acquire_lease(db_session, "worker-a", settings) is True
    # A second process is refused while the first lease is alive.
    assert acquire_lease(db_session, "worker-b", settings) is False

    assert renew_lease(db_session, "worker-a", settings) is True
    assert renew_lease(db_session, "worker-b", settings) is False

    release_lease(db_session, "worker-a")
    assert acquire_lease(db_session, "worker-b", settings) is True


def test_expired_lease_is_recoverable_after_a_crash(db_session: Session) -> None:
    settings = get_settings()
    assert acquire_lease(db_session, "crashed-worker", settings) is True

    lease = db_session.get(WorkerLease, 1)
    lease.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    assert acquire_lease(db_session, "replacement", settings) is True
    assert db_session.get(WorkerLease, 1).owner == "replacement"


def test_worker_lease_table_exists_on_sqlite_with_foreign_keys_on(
    db_session: Session,
) -> None:
    # The fixture enables PRAGMA foreign_keys; prove it so cascade tests mean
    # something.
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert db_session.get(WorkerLease, 1) is None
