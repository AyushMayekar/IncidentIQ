from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from incidentiq.api.routes import evidence as evidence_routes
from incidentiq.api.routes.evidence import MAX_UPLOAD_BYTES, sanitize_filename
from incidentiq.models.entities import EvidenceSource

EVIDENCE_TYPES = [
    "application_log",
    "infrastructure_log",
    "metrics",
    "trace",
    "deployment_event",
    "alert",
    "configuration",
    "manual_context",
]


def make_incident(client: TestClient, title: str = "Checkout API 500s") -> str:
    response = client.post(
        "/api/v1/incidents",
        json={
            "title": title,
            "description": "Elevated 500 errors on checkout.",
            "service": "checkout",
            "severity": "high",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(
    client: TestClient,
    incident_id: str,
    content: bytes,
    filename: str = "app.log",
    evidence_type: str = "application_log",
):
    return client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        files={"file": (filename, content, "application/octet-stream")},
        data={"evidence_type": evidence_type},
    )


def evidence_list(client: TestClient, incident_id: str) -> list[dict]:
    response = client.get(f"/api/v1/incidents/{incident_id}/evidence")
    assert response.status_code == 200, response.text
    return response.json()


def add_evidence_row(
    db: Session,
    incident_id: str,
    name: str,
    content: str,
    created_at: datetime,
    evidence_type: str | None = "application_log",
) -> EvidenceSource:
    data = content.encode("utf-8")
    row = EvidenceSource(
        incident_id=UUID(incident_id),
        source_name=name,
        evidence_type=evidence_type,
        content_type="text/plain; charset=utf-8",
        raw_content=content,
        content_hash=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        parse_status="not_required",
        created_at=created_at,
    )
    db.add(row)
    db.commit()
    return row


# --- successful uploads -----------------------------------------------------


def test_upload_log_success(client: TestClient) -> None:
    incident_id = make_incident(client)
    content = b"2026-10-31T10:00:00Z ERROR payment gateway timeout\n"

    response = upload(client, incident_id, content, "checkout.log", "application_log")

    assert response.status_code == 201
    body = response.json()
    assert body["incident_id"] == incident_id
    assert body["source_name"] == "checkout.log"
    assert body["evidence_type"] == "application_log"
    assert body["content_type"] == "text/plain; charset=utf-8"
    assert body["byte_size"] == len(content)
    assert body["content_hash"] == hashlib.sha256(content).hexdigest()
    assert body["parse_status"] == "queued"
    assert body["record_count"] == 0
    assert body["processed_at"] is None
    assert "id" in body and "created_at" in body
    assert "raw_content" not in body


def test_upload_txt_success(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"deploy v1.2.3 started", "notes.txt", "manual_context")

    assert response.status_code == 201
    assert response.json()["source_name"] == "notes.txt"
    assert response.json()["evidence_type"] == "manual_context"


@pytest.mark.parametrize("evidence_type", EVIDENCE_TYPES)
def test_every_allowed_evidence_type_is_accepted(client: TestClient, evidence_type: str) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"sample", "x.log", evidence_type)

    assert response.status_code == 201
    assert response.json()["evidence_type"] == evidence_type


@pytest.mark.parametrize("filename", ["APP.LOG", "Notes.TXT", "mixed.Log"])
def test_extension_check_is_case_insensitive(client: TestClient, filename: str) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"hello", filename)

    assert response.status_code == 201
    assert response.json()["source_name"] == filename


def test_byte_size_counts_bytes_not_characters(client: TestClient) -> None:
    incident_id = make_incident(client)
    content = "héllo €uro ✓\n".encode("utf-8")
    assert len(content) > len(content.decode("utf-8"))

    response = upload(client, incident_id, content)

    assert response.status_code == 201
    assert response.json()["byte_size"] == len(content)
    assert response.json()["content_hash"] == hashlib.sha256(content).hexdigest()


def test_upload_at_exact_size_limit_is_accepted(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"a" * MAX_UPLOAD_BYTES)

    assert response.status_code == 201
    assert response.json()["byte_size"] == MAX_UPLOAD_BYTES


# --- form field validation --------------------------------------------------


def test_missing_evidence_type_is_rejected(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        files={"file": ("app.log", b"hello", "text/plain")},
    )

    assert response.status_code == 422
    assert evidence_list(client, incident_id) == []


def test_invalid_evidence_type_is_rejected(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"hello", evidence_type="screenshot")

    assert response.status_code == 422
    assert evidence_list(client, incident_id) == []


def test_missing_file_is_rejected(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        data={"evidence_type": "application_log"},
    )

    assert response.status_code == 422


# --- file validation ---------------------------------------------------------


@pytest.mark.parametrize(
    "filename", ["data.csv", "app.log.exe", "run.sh", "README", "app", ".log", "image.png"]
)
def test_unsupported_extension_is_rejected(client: TestClient, filename: str) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"hello", filename)

    assert response.status_code == 400
    assert evidence_list(client, incident_id) == []


def test_empty_upload_is_rejected(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"")

    assert response.status_code == 400
    assert evidence_list(client, incident_id) == []


def test_invalid_utf8_is_rejected(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"valid start \xff\xfe invalid bytes")

    assert response.status_code == 400
    assert "UTF-8" in response.json()["detail"]
    assert evidence_list(client, incident_id) == []


def test_nul_byte_is_rejected(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"line one\x00line two")

    assert response.status_code == 400
    assert "NUL" in response.json()["detail"]
    assert evidence_list(client, incident_id) == []


def test_oversized_upload_is_rejected(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"a" * (MAX_UPLOAD_BYTES + 1))

    assert response.status_code == 413
    assert evidence_list(client, incident_id) == []


def test_overlong_filename_is_rejected(client: TestClient) -> None:
    incident_id = make_incident(client)
    too_long = "a" * 252 + ".log"
    assert len(too_long) == 256

    response = upload(client, incident_id, b"hello", too_long)

    assert response.status_code == 400
    assert evidence_list(client, incident_id) == []


def test_path_components_are_stripped_from_filename(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = upload(client, incident_id, b"hello", "../../etc/secrets/app.log")

    assert response.status_code == 201
    assert response.json()["source_name"] == "app.log"


def test_sanitize_filename_handles_windows_and_posix_paths() -> None:
    assert sanitize_filename("C:\\Users\\ayush\\logs\\app.log") == "app.log"
    assert sanitize_filename("..\\..\\windows\\system.log") == "system.log"
    assert sanitize_filename("/var/log/app.log") == "app.log"
    assert sanitize_filename("  spaced.log  ") == "spaced.log"
    assert sanitize_filename("plain.txt") == "plain.txt"


@pytest.mark.parametrize(
    "raw", [None, "", "   ", "..", ".", "logs/", "logs\\", "bad\x00name.log", "new\nline.log"]
)
def test_sanitize_filename_rejects_bad_names(raw: str | None) -> None:
    with pytest.raises(HTTPException) as exc_info:
        sanitize_filename(raw)
    assert exc_info.value.status_code == 400


# --- missing incident / evidence --------------------------------------------


def test_upload_to_missing_incident_returns_404(client: TestClient) -> None:
    response = upload(client, str(uuid4()), b"hello")

    assert response.status_code == 404


def test_list_for_missing_incident_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/incidents/{uuid4()}/evidence")

    assert response.status_code == 404


def test_content_for_missing_incident_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/incidents/{uuid4()}/evidence/{uuid4()}/content")

    assert response.status_code == 404


def test_content_for_missing_evidence_returns_404(client: TestClient) -> None:
    incident_id = make_incident(client)

    response = client.get(f"/api/v1/incidents/{incident_id}/evidence/{uuid4()}/content")

    assert response.status_code == 404


# --- listing -----------------------------------------------------------------


def test_list_returns_metadata_and_never_raw_content(client: TestClient) -> None:
    incident_id = make_incident(client)
    secret = b"password=SUPER_SECRET_VALUE\n"
    upload(client, incident_id, secret, "config.txt", "configuration")

    response = client.get(f"/api/v1/incidents/{incident_id}/evidence")

    assert response.status_code == 200
    assert "SUPER_SECRET_VALUE" not in response.text
    items = response.json()
    assert len(items) == 1
    assert "raw_content" not in items[0]
    assert set(items[0]) == {
        "id",
        "incident_id",
        "source_name",
        "evidence_type",
        "content_type",
        "content_hash",
        "byte_size",
        "parse_status",
        "created_at",
        "error_message",
        "record_count",
        "processed_at",
        "processing_duration_ms",
    }


def test_list_is_scoped_to_incident_and_newest_first(
    client: TestClient, db_session: Session
) -> None:
    incident_a = make_incident(client, "Incident A")
    incident_b = make_incident(client, "Incident B")
    t = lambda hour: datetime(2026, 10, 31, hour, 0, tzinfo=timezone.utc)  # noqa: E731

    add_evidence_row(db_session, incident_a, "oldest.log", "one", t(8))
    add_evidence_row(db_session, incident_a, "legacy.log", "two", t(9), evidence_type=None)
    add_evidence_row(db_session, incident_a, "newest.log", "three", t(10))
    add_evidence_row(db_session, incident_b, "other.log", "four", t(11))

    items = evidence_list(client, incident_a)

    assert [item["source_name"] for item in items] == ["newest.log", "legacy.log", "oldest.log"]
    assert all(item["incident_id"] == incident_a for item in items)
    legacy = next(item for item in items if item["source_name"] == "legacy.log")
    assert legacy["evidence_type"] is None

    assert [item["source_name"] for item in evidence_list(client, incident_b)] == ["other.log"]


# --- content retrieval -------------------------------------------------------


def test_content_returns_exact_original_text(client: TestClient) -> None:
    incident_id = make_incident(client)
    original = "line one\r\nline two with ünïcödé ✓ and tabs\t\r\n\r\nno trailing newline"
    original_bytes = original.encode("utf-8")
    created = upload(client, incident_id, original_bytes, "mixed.log").json()

    response = client.get(
        f"/api/v1/incidents/{incident_id}/evidence/{created['id']}/content"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.content == original_bytes
    assert response.text == original


def test_content_cannot_be_read_through_wrong_incident(client: TestClient) -> None:
    incident_a = make_incident(client, "Incident A")
    incident_b = make_incident(client, "Incident B")
    created = upload(client, incident_a, b"private to A").json()

    wrong = client.get(f"/api/v1/incidents/{incident_b}/evidence/{created['id']}/content")
    right = client.get(f"/api/v1/incidents/{incident_a}/evidence/{created['id']}/content")

    assert wrong.status_code == 404
    assert "private to A" not in wrong.text
    assert right.status_code == 200
    assert right.text == "private to A"


# --- duplicates --------------------------------------------------------------


def test_duplicate_content_in_same_incident_returns_409(client: TestClient) -> None:
    incident_id = make_incident(client)
    content = b"identical bytes\n"
    assert upload(client, incident_id, content, "first.log").status_code == 201

    # Different filename and evidence type: duplicate is decided by content only.
    response = upload(client, incident_id, content, "second.txt", "alert")

    assert response.status_code == 409
    assert len(evidence_list(client, incident_id)) == 1


def test_same_content_in_different_incidents_is_allowed(client: TestClient) -> None:
    incident_a = make_incident(client, "Incident A")
    incident_b = make_incident(client, "Incident B")
    content = b"shared evidence\n"

    first = upload(client, incident_a, content)
    second = upload(client, incident_b, content)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["content_hash"] == second.json()["content_hash"]


def test_concurrent_duplicate_insert_returns_409_and_session_stays_usable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = make_incident(client)
    content = b"raced content\n"
    assert upload(client, incident_id, content).status_code == 201

    # Simulate losing a race: the friendly pre-check misses, so the database
    # unique constraint is what rejects the insert. The post-rollback re-check
    # then sees the winner's row.
    calls: list[int] = []

    def racing_duplicate_check(db, incident_id, content_hash) -> bool:
        calls.append(1)
        return len(calls) > 1

    monkeypatch.setattr(evidence_routes, "_duplicate_exists", racing_duplicate_check)

    response = upload(client, incident_id, content, "loser.log")

    assert response.status_code == 409
    assert len(calls) == 2
    monkeypatch.undo()
    # The shared session must not be left in a failed transaction.
    assert len(evidence_list(client, incident_id)) == 1
    assert upload(client, incident_id, b"different content").status_code == 201


# --- integrity and schema ----------------------------------------------------


def test_deleting_incident_cascades_to_evidence(
    client: TestClient, db_session: Session
) -> None:
    incident_id = make_incident(client)
    upload(client, incident_id, b"will be cascaded")

    assert client.delete(f"/api/v1/incidents/{incident_id}").status_code == 204

    remaining = db_session.scalar(select(func.count()).select_from(EvidenceSource))
    assert remaining == 0


def test_evidence_endpoints_appear_in_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    collection = paths["/api/v1/incidents/{incident_id}/evidence"]
    assert "post" in collection
    assert "get" in collection
    assert "201" in collection["post"]["responses"]
    assert "multipart/form-data" in collection["post"]["requestBody"]["content"]

    content_path = paths["/api/v1/incidents/{incident_id}/evidence/{evidence_id}/content"]
    assert "get" in content_path

    form_schema_name = collection["post"]["requestBody"]["content"]["multipart/form-data"][
        "schema"
    ]["$ref"].rsplit("/", 1)[-1]
    form_properties = schema["components"]["schemas"][form_schema_name]["properties"]
    assert {"file", "evidence_type"} <= set(form_properties)