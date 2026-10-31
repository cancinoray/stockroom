"""Pin ``/api/version`` to the settings it is supposed to report.

The endpoint must read process settings on every request rather than returning
constants, so these tests set the environment, clear the settings cache and
assert the response echoes those values back.

``backend/config.py`` loads ``.env`` relative to the working directory, so each
test runs inside ``tmp_path`` to guarantee no ambient ``.env`` leaks in.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Make every test load settings afresh, before and after it runs."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_version_reads_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STOCKROOM_COMMIT", "abc1234")
    monkeypatch.setenv("STOCKROOM_BUILD_TIME", "2025-01-02T03:04:05Z")
    monkeypatch.setenv("STOCKROOM_ENVIRONMENT", "staging")
    get_settings.cache_clear()

    response = client.get("/api/version")

    assert response.status_code == 200
    body = response.json()
    assert body["commit"] == "abc1234"
    assert body["build_time"] == "2025-01-02T03:04:05Z"
    assert body["environment"] == "staging"


def test_version_reports_unknown_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STOCKROOM_COMMIT", raising=False)
    monkeypatch.delenv("STOCKROOM_BUILD_TIME", raising=False)
    monkeypatch.delenv("STOCKROOM_ENVIRONMENT", raising=False)
    get_settings.cache_clear()

    response = client.get("/api/version")

    assert response.status_code == 200
    body = response.json()
    assert body["commit"] == "unknown"
    assert body["build_time"] == "unknown"
