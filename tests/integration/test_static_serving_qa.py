"""QA verification for issue #46 (T5.1) — independent coverage of AC5.

Added by QA in a fresh session. ``tests/integration/test_static_serving.py``
proves that dotfiles and encoded ``..`` forms return ``404``, but every file
those tests reach for lives *inside* the fixture build. AC5's second clause —
the fallback cannot read outside ``frontend/dist`` — had no test that could
fail: deleting ``candidate.is_relative_to(root)`` from ``_mount_frontend`` in
``backend/main.py`` left all 18 tests green, because the dotfile and
missing-file rules answer those paths first.

These tests put the secret outside the build directory, which is the situation
the criterion describes. The symlink case is the one only the resolved-path
containment check can catch, so it fails when that check is removed.

No product code is changed and no real frontend build is needed.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app

# The DSN the fallback would serve if it escaped the build directory.
SECRET_DSN = "postgresql+psycopg://stockroom:hunter2@db.internal:5432/stockroom"


@pytest.fixture()
def build(tmp_path: Path) -> tuple[Path, Path]:
    """A build directory plus a secret file beside it, never inside it."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><div id="root"></div>', encoding="utf-8")
    secret = tmp_path / "escaped.secret"
    secret.write_text(f"STOCKROOM_DATABASE_URL={SECRET_DSN}\n", encoding="utf-8")
    return dist, secret


@pytest.fixture()
def client(build: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A real app pointed at the fixture build, with no database configured."""
    dist, _ = build
    monkeypatch.setenv("STOCKROOM_FRONTEND_DIST", str(dist))
    monkeypatch.delenv("STOCKROOM_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/escaped.secret",
        "/%2e%2e%2fescaped.secret",
        "/orders/%2e%2e/%2e%2e/escaped.secret",
        "/assets/%2e%2e/%2e%2e/escaped.secret",
    ],
)
def test_a_file_outside_the_build_is_never_served(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404, response.text
    assert "hunter2" not in response.text
    assert "STOCKROOM_DATABASE_URL" not in response.text


def test_a_symlink_out_of_the_build_is_not_followed(
    build: tuple[Path, Path], client: TestClient
) -> None:
    """Only the resolved-path containment check can answer this one.

    ``notes`` has no extension and is not a dotfile, so neither the
    missing-file rule nor the dotfile rule can be what returns ``404``.
    """
    dist, secret = build
    (dist / "notes").symlink_to(secret)

    response = client.get("/notes")

    assert response.status_code == 404, response.text
    assert "hunter2" not in response.text
