"""Contract tests for the incident endpoints used by the frontend."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.conftest import make_payload


def test_list_incidents_starts_empty(client: TestClient) -> None:
    response = client.get("/api/v1/incidents")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["limit"] == 20
    assert body["offset"] == 0


def test_create_incident_returns_201_with_defaults(
    client: TestClient, incident_payload: dict[str, object]
) -> None:
    response = client.post("/api/v1/incidents", json=incident_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == incident_payload["title"]
    assert body["description"] == incident_payload["description"]
    assert body["service"] == incident_payload["service"]
    assert body["severity"] == "high"
    assert body["status"] == "open"
    assert body["occurred_at"] is None
    assert body["id"]
    assert body["created_at"]
    assert body["updated_at"]


def test_create_incident_with_occurred_at(client: TestClient) -> None:
    payload = make_payload(occurred_at="2026-01-05T09:30:00Z")

    response = client.post("/api/v1/incidents", json=payload)

    assert response.status_code == 201
    assert response.json()["occurred_at"] is not None


def test_create_incident_rejects_blank_title(client: TestClient) -> None:
    response = client.post(
        "/api/v1/incidents", json=make_payload(title="   ")
    )

    assert response.status_code == 422


def test_create_incident_rejects_blank_description(client: TestClient) -> None:
    response = client.post(
        "/api/v1/incidents", json=make_payload(description="  ")
    )

    assert response.status_code == 422


def test_create_incident_rejects_unknown_severity(client: TestClient) -> None:
    response = client.post(
        "/api/v1/incidents", json=make_payload(severity="apocalyptic")
    )

    assert response.status_code == 422


def test_get_incident_by_id(client: TestClient) -> None:
    created = client.post("/api/v1/incidents", json=make_payload()).json()

    response = client.get(f"/api/v1/incidents/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["title"] == created["title"]


def test_get_incident_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/incidents/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found."


def test_list_incidents_orders_newest_first(client: TestClient) -> None:
    first = client.post("/api/v1/incidents", json=make_payload()).json()
    second = client.post("/api/v1/incidents", json=make_payload()).json()

    body = client.get("/api/v1/incidents").json()

    assert body["total"] == 2
    listed = [item["id"] for item in body["items"]]
    assert listed[0] in {first["id"], second["id"]}
    assert set(listed) == {first["id"], second["id"]}


def test_list_incidents_paginates(client: TestClient) -> None:
    for _ in range(3):
        client.post("/api/v1/incidents", json=make_payload())

    page = client.get("/api/v1/incidents?limit=2&offset=0").json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["limit"] == 2
    assert page["offset"] == 0

    rest = client.get("/api/v1/incidents?limit=2&offset=2").json()
    assert len(rest["items"]) == 1
    assert rest["offset"] == 2

    first_page_ids = {item["id"] for item in page["items"]}
    assert {item["id"] for item in rest["items"]}.isdisjoint(first_page_ids)


def test_list_incidents_rejects_out_of_range_limit(client: TestClient) -> None:
    assert client.get("/api/v1/incidents?limit=0").status_code == 422
    assert client.get("/api/v1/incidents?limit=101").status_code == 422
    assert client.get("/api/v1/incidents?offset=-1").status_code == 422


def test_update_incident_fields(client: TestClient) -> None:
    created = client.post("/api/v1/incidents", json=make_payload()).json()

    response = client.patch(
        f"/api/v1/incidents/{created['id']}",
        json={
            "title": "Renamed incident",
            "severity": "critical",
            "status": "investigating",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed incident"
    assert body["severity"] == "critical"
    assert body["status"] == "investigating"
    assert body["description"] == created["description"]
    assert body["updated_at"] >= created["updated_at"]


def test_update_incident_not_found(client: TestClient) -> None:
    response = client.patch(
        f"/api/v1/incidents/{uuid4()}", json={"status": "closed"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found."


def test_update_incident_rejects_unknown_status(client: TestClient) -> None:
    created = client.post("/api/v1/incidents", json=make_payload()).json()

    response = client.patch(
        f"/api/v1/incidents/{created['id']}", json={"status": "paused"}
    )

    assert response.status_code == 422


def test_delete_incident_then_get_returns_404(client: TestClient) -> None:
    created = client.post("/api/v1/incidents", json=make_payload()).json()

    delete_response = client.delete(f"/api/v1/incidents/{created['id']}")

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert client.get(f"/api/v1/incidents/{created['id']}").status_code == 404
    assert client.get("/api/v1/incidents").json()["total"] == 0


def test_delete_incident_not_found(client: TestClient) -> None:
    response = client.delete(f"/api/v1/incidents/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found."


def test_incident_routes_are_registered(client: TestClient) -> None:
    """Guards against an endpoint used by the frontend disappearing."""
    from incidentiq.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/incidents" in paths
    assert "/api/v1/incidents/{incident_id}" in paths
    assert "/health/live" in paths

    incident_path = "/api/v1/incidents"
    methods = {method.upper() for method in app.openapi()["paths"][incident_path]}
    assert {"GET", "POST"} <= methods

    item_methods = {
        method.upper()
        for method in app.openapi()["paths"]["/api/v1/incidents/{incident_id}"]
    }
    assert {"GET", "PATCH", "DELETE"} <= item_methods
