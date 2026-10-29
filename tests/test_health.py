"""Health endpoint contract."""

from fastapi.testclient import TestClient


def test_health_live_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
