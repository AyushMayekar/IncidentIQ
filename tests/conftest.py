"""Shared pytest fixtures.

The suite never touches the real PostgreSQL database or the project ``.env``:
database settings are injected explicitly *before* the application is imported,
so pydantic-settings has no reason to open the developer's environment file.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

# These must be set before any ``incidentiq`` import: importing the app builds
# the settings object and the SQLAlchemy engine from them.
os.environ["INCIDENTIQ_ENV_FILE"] = "/tmp/opencode/does-not-exist.env"
os.environ.setdefault("APP_ENV", "test")
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from incidentiq.api.dependencies import get_db  # noqa: E402
from incidentiq.main import app  # noqa: E402
from incidentiq.models.entities import Incident  # noqa: E402

# Only the incidents table exists in tests: the other tables use PostgreSQL
# specific types (JSONB) that SQLite cannot compile, and the first vertical
# slice does not expose them through any endpoint.
TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TEST_SESSION = sessionmaker(bind=TEST_ENGINE, autoflush=False, expire_on_commit=False)

Incident.__table__.create(bind=TEST_ENGINE, checkfirst=True)


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    """Give every test an empty database, without ever using the real one."""
    with TEST_ENGINE.begin() as connection:
        connection.execute(Incident.__table__.delete())
    yield
    with TEST_ENGINE.begin() as connection:
        connection.execute(Incident.__table__.delete())


@pytest.fixture()
def db_session() -> Iterator[Session]:
    session = TEST_SESSION()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    """HTTP client wired to the in-memory database."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def incident_payload() -> dict[str, object]:
    return {
        "title": "Checkout API elevated 5xx errors",
        "description": "Checkout requests are failing with HTTP 502 for ~12% of sessions.",
        "service": "checkout-api",
        "severity": "high",
    }


def make_payload(**overrides: object) -> dict[str, object]:
    """Build a valid incident payload with optional field overrides."""
    payload: dict[str, object] = {
        "title": f"Incident {uuid4().hex[:8]}",
        "description": "Automatically generated description for the test case.",
        "service": "payments-api",
        "severity": "medium",
    }
    payload.update(overrides)
    return payload
