from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

os.environ["INCIDENTIQ_ENV_FILE"] = "/tmp/opencode/does-not-exist.env"
os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from incidentiq.api.dependencies import get_db
from incidentiq.main import app
from incidentiq.models.entities import (
    EvidenceJob,
    EvidenceSource,
    Incident,
    ParsedEvidenceRecord,
    WorkerLease,
)

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(TEST_ENGINE, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    # SQLite ignores foreign keys unless enabled per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TEST_SESSION = sessionmaker(bind=TEST_ENGINE, autoflush=False, expire_on_commit=False)

# Only the tables the API tests need; other models use PostgreSQL JSONB.
Incident.__table__.create(bind=TEST_ENGINE, checkfirst=True)
EvidenceSource.__table__.create(bind=TEST_ENGINE, checkfirst=True)
EvidenceJob.__table__.create(bind=TEST_ENGINE, checkfirst=True)
ParsedEvidenceRecord.__table__.create(bind=TEST_ENGINE, checkfirst=True)
WorkerLease.__table__.create(bind=TEST_ENGINE, checkfirst=True)


def _wipe_tables() -> None:
    with TEST_ENGINE.begin() as connection:
        # Children first to respect foreign keys.
        connection.execute(ParsedEvidenceRecord.__table__.delete())
        connection.execute(EvidenceJob.__table__.delete())
        connection.execute(WorkerLease.__table__.delete())
        connection.execute(EvidenceSource.__table__.delete())
        connection.execute(Incident.__table__.delete())


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    _wipe_tables()
    yield
    _wipe_tables()

@pytest.fixture
def incident_payload() -> dict[str, object]:
    return make_payload()

@pytest.fixture()
def db_session() -> Iterator[Session]:
    session = TEST_SESSION()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def make_payload(**overrides: object) -> dict[str, object]:
    """Build a valid incident payload with optional field overrides."""
    payload: dict[str, object] = {
        "title": f"Incident {uuid4().hex[:8]}",
        "description": "Automatically generated description for the test case.",
        "service": "payments-api",
        "severity": "high",
    }
    payload.update(overrides)
    return payload
