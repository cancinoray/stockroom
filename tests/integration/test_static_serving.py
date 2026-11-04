"""One container serves the API and the built React app (T5.1, issue #46).

The app mounts ``frontend/dist`` at the root once a build exists. These tests
point ``STOCKROOM_FRONTEND_DIST`` at a fixture directory instead of a real
build, so they prove the mount without Node and without a ``frontend/dist`` on
a fresh clone. They cover AC2-AC7 and the schema half of AC8; the image,
compose, healthcheck and non-root claims are the e2e commands in the PR.

Routes are matched in order, so the API wins first, then the built files, then
the client-route fallback. A missing asset and anything outside the build stay
``404`` rather than turning into ``index.html``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app

HASHED_ASSET = "assets/index-b00b1e5.js"
ORDER_ID = "018f3c1e-6f4a-7c2b-9a10-5d6e7f8a9b0c"
# A DSN the traversal tests would leak if the fallback escaped frontend/dist.
SECRET_DSN = "postgresql+psycopg://stockroom:hunter2@db.internal:5432/stockroom"

INDEX_HTML = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <title>Stockroom — Main</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/{HASHED_ASSET}"></script>
  </body>
</html>
"""


@pytest.fixture()
def dist(tmp_path: Path) -> Path:
    """A stand-in for ``frontend/dist``, including a file it must not leak."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (tmp_path / HASHED_ASSET).write_text("console.log('stockroom');\n", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'/>\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(f"STOCKROOM_DATABASE_URL={SECRET_DSN}\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(dist: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A real app pointed at the fixture build, with no database configured."""
    monkeypatch.setenv("STOCKROOM_FRONTEND_DIST", str(dist))
    monkeypatch.delenv("STOCKROOM_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


# --- AC2: / serves the built app ---------------------------------------------


def test_root_serves_the_built_index_html(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="root"' in response.text
    assert f"/{HASHED_ASSET}" in response.text


def test_built_files_are_served_directly(client: TestClient) -> None:
    asset = client.get(f"/{HASHED_ASSET}")
    assert asset.status_code == 200
    assert asset.text == "console.log('stockroom');\n"

    icon = client.get("/favicon.svg")
    assert icon.status_code == 200
    assert "image/svg+xml" in icon.headers["content-type"]


# --- AC3: client routes fall back to the app shell ---------------------------


@pytest.mark.parametrize("path", ["/orders", f"/orders/{ORDER_ID}", "/orders/not-a-built-file"])
def test_client_routes_return_the_app_shell(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == INDEX_HTML


# --- AC4: a missing asset is still a 404 -------------------------------------


def test_a_missing_asset_is_a_404_not_the_app_shell(client: TestClient) -> None:
    response = client.get("/assets/does-not-exist.js")

    assert response.status_code == 404
    assert 'id="root"' not in response.text


def test_a_missing_root_file_is_a_404_not_the_app_shell(client: TestClient) -> None:
    response = client.get("/does-not-exist.js")

    assert response.status_code == 404
    assert 'id="root"' not in response.text


# --- AC5: the fallback cannot read outside frontend/dist ---------------------


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/../.env",
        "/%2e%2e/.env",
        "/%2e%2e/%2e%2e/.env",
        "/orders/%2e%2e/%2e%2e/.env",
        "/assets/%2e%2e/%2e%2e/.env",
        "/..%2f..%2f.env",
    ],
)
def test_traversal_attempts_are_404_and_never_leak(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404, response.text
    assert "hunter2" not in response.text
    assert "STOCKROOM_DATABASE_URL" not in response.text


# --- AC6: the API is untouched -----------------------------------------------


def test_the_api_answers_before_the_fallback(client: TestClient) -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "db": "not_configured"}

    version = client.get("/api/version")
    assert version.status_code == 200
    assert version.headers["content-type"].startswith("application/json")
    assert version.json()["version"]


def test_an_unknown_api_path_keeps_the_problem_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "not_found"
    assert body["trace_id"]
    assert 'id="root"' not in response.text


# --- AC7: no build on disk, no breakage --------------------------------------


def test_without_a_build_the_spa_mount_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STOCKROOM_FRONTEND_DIST", str(tmp_path / "missing"))
    monkeypatch.delenv("STOCKROOM_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            version = client.get("/api/version")
            assert version.status_code == 200
            assert version.headers["content-type"].startswith("application/json")

            # No build means no app shell to fall back to.
            root = client.get("/")
            assert root.status_code == 404
    finally:
        get_settings.cache_clear()


# --- AC8: the fallback stays out of the generated schema ---------------------


def test_the_spa_fallback_is_not_in_the_schema(client: TestClient) -> None:
    paths = create_app().openapi()["paths"]

    assert "/api/version" in paths
    assert not [path for path in paths if "full_path" in path]
