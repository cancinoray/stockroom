"""T5.3 (issue #48) AC10: the post-deploy smoke helper.

``scripts/release-smoke.sh`` must check ``/healthz``, ``GET /`` and
``GET /api/version`` against a running host and exit non-zero on any failure.
These tests run the real script against a stub HTTP host.
"""

from __future__ import annotations

import http.server
import socket
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release-smoke.sh"

Routes = dict[str, tuple[str, str]]

HEALTHY: Routes = {
    "/healthz": ("application/json", '{"status":"ok","db":"ok"}'),
    "/": ("text/html; charset=utf-8", '<!doctype html><div id="root"></div>'),
    "/api/version": (
        "application/json",
        '{"version":"0.1.0","commit":"f4c2184","build_time":"x","environment":"test"}',
    ),
}


@contextmanager
def _host(routes: Routes) -> Iterator[str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            entry = routes.get(self.path.split("?")[0])
            if entry is None:
                self.send_error(404)
                return
            content_type, body = entry
            payload = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _smoke(base: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), base], capture_output=True, text=True)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_smoke_passes_on_a_healthy_host() -> None:
    with _host(HEALTHY) as base:
        result = _smoke(base)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "smoke passed" in result.stdout
    for check in ("ok    /healthz", "ok    GET /", "ok    /api/version"):
        assert check in result.stdout, check


def test_smoke_fails_when_healthz_does_not_report_the_database() -> None:
    routes = dict(HEALTHY, **{"/healthz": ("application/json", '{"status":"ok"}')})
    with _host(routes) as base:
        result = _smoke(base)

    assert result.returncode != 0
    assert "FAIL  /healthz" in result.stdout


def test_smoke_fails_when_the_root_is_not_the_built_ui() -> None:
    routes = dict(HEALTHY, **{"/": ("application/json", '{"detail":"Not Found"}')})
    with _host(routes) as base:
        result = _smoke(base)

    assert result.returncode != 0
    assert "FAIL  GET /" in result.stdout


def test_smoke_fails_when_version_metadata_is_incomplete() -> None:
    routes = dict(HEALTHY, **{"/api/version": ("application/json", '{"version":"0.1.0"}')})
    with _host(routes) as base:
        result = _smoke(base)

    assert result.returncode != 0
    assert "FAIL  /api/version" in result.stdout


def test_smoke_fails_on_a_dead_port() -> None:
    result = _smoke(f"http://127.0.0.1:{_free_port()}")

    assert result.returncode != 0
    assert "smoke FAILED" in result.stdout
    assert result.stdout.count("FAIL  ") == 3
