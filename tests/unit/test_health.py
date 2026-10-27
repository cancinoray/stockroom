from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_healthz_returns_ok() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "not_configured"}


def test_version_reports_build_metadata() -> None:
    response = client.get("/api/version")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "0.1.0"
    assert set(body) == {"version", "commit", "build_time", "environment"}
