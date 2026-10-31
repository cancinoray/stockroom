from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.db.session import probe_database
from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_dependency_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_healthz_returns_ok() -> None:
    app.dependency_overrides[probe_database] = lambda: "ok"

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_healthz_reports_not_configured() -> None:
    app.dependency_overrides[probe_database] = lambda: "not_configured"

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "not_configured"}


def test_version_reports_build_metadata() -> None:
    response = client.get("/api/version")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "0.1.0"
    assert set(body) == {"version", "commit", "build_time", "environment"}
