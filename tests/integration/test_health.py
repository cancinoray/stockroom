"""``GET /healthz`` reports database reachability against a real Postgres."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import app

UNREACHABLE_DATABASE_URL = (
    "postgresql+psycopg://nobody:nobody@127.0.0.1:1/stockroom?connect_timeout=2"
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    yield
    get_settings.cache_clear()


def _client_pointed_at(url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
    get_settings.cache_clear()
    return TestClient(app)


def test_healthz_reports_ok_when_database_is_reachable(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_pointed_at(database_url, monkeypatch)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_healthz_returns_503_when_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _client_pointed_at(UNREACHABLE_DATABASE_URL, monkeypatch)

    with caplog.at_level(logging.WARNING, logger="backend.db.session"):
        response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "unreachable"}
    assert any("health probe failed" in record.getMessage().lower() for record in caplog.records)
