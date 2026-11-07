"""verify-recovery.sh against fake Prometheus and app responses (#62).

The script is a shell entry point with an embedded stdlib-only checker, so the
test drives the real file against a loopback HTTP server: one recovered run and
one failed run per check. No Docker, no Prometheus, no network.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "on-call-engineer" / "verify-recovery.sh"
SKILL = ROOT / ".agents" / "skills" / "investigate-alert" / "SKILL.md"
INCIDENT_ID = "stockroom-order-error-rate-high-324f01034b2a-1794026992"
ALERT = "StockroomOrderErrorRateHigh"
EXPR = "sum(rate(stockroom_orders_failed_total[5m])) > 0.05"

Route = tuple[int, Any] | Callable[[str], tuple[int, Any]]


class Handler(BaseHTTPRequestHandler):
    routes: dict[str, Route] = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server's API
        parsed = urlparse(self.path)
        route = self.server.routes.get(parsed.path)
        if route is None:
            status, payload = 404, {"error": "not found"}
        elif callable(route):
            status, payload = route(parsed.query)
        else:
            status, payload = route
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        return


@contextmanager
def fake_stack(routes: dict[str, Route]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.routes = routes
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def healthy_routes(*, query_result: list[Any] | None = None) -> dict[str, Route]:
    def query(querystring: str) -> tuple[int, Any]:
        asked = parse_qs(querystring).get("query", [""])[0]
        assert asked == EXPR, asked
        return 200, {
            "status": "success",
            "data": {"resultType": "vector", "result": query_result or []},
        }

    return {
        "/api/v1/alerts": (200, {"status": "success", "data": {"alerts": []}}),
        "/api/v1/query": query,
        "/healthz": (200, {"status": "ok", "db": "ok"}),
        "/api/invariants": (200, {"ok": True, "violations": []}),
    }


def write_incident(tmp_path: Path, expr: str | None = EXPR) -> Path:
    incidents = tmp_path / "incidents"
    incidents.mkdir()
    record = {
        "incident_id": INCIDENT_ID,
        "alert": {
            "name": ALERT,
            "severity": "critical",
            "environment": "development",
            "version": "0.1.0",
            "dashboard_url": "http://localhost:3000/d/stockroom-order-journey",
            "rule": {"expr": expr, "for": "1m"},
        },
        "action": "fix",
    }
    (incidents / f"{INCIDENT_ID}.json").write_text(json.dumps(record), encoding="utf-8")
    return incidents


def verify(
    base: str, incidents: Path, *, app_url: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        {
            "PROMETHEUS_URL": base,
            "STOCKROOM_APP_URL": app_url or base,
            "ONCALL_INCIDENTS_DIR": str(incidents),
        }
    )
    return subprocess.run(
        ["sh", str(SCRIPT), INCIDENT_ID],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def report(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(completed.stdout.strip().splitlines()[-1])


def checks(document: dict[str, Any]) -> dict[str, bool]:
    return {item["name"]: item["ok"] for item in document["checks"]}


def test_a_recovered_incident_exits_zero(tmp_path: Path) -> None:
    incidents = write_incident(tmp_path)
    with fake_stack(healthy_routes()) as base:
        completed = verify(base, incidents)

    assert completed.returncode == 0, completed.stderr
    document = report(completed)
    assert document["recovered"] is True
    assert document["incident_id"] == INCIDENT_ID
    assert document["alert"] == ALERT
    assert document["rule"] == {"expr": EXPR, "for": "1m"}
    assert checks(document) == {
        "alert_absent": True,
        "impact_below_threshold": True,
        "app_healthz": True,
        "app_invariants": True,
    }


def test_an_alert_still_listed_is_not_recovery(tmp_path: Path) -> None:
    incidents = write_incident(tmp_path)
    routes = healthy_routes()
    routes["/api/v1/alerts"] = (
        200,
        {
            "status": "success",
            "data": {
                "alerts": [
                    {
                        "labels": {"alertname": ALERT},
                        "state": "firing",
                        "annotations": {},
                    }
                ]
            },
        },
    )
    with fake_stack(routes) as base:
        completed = verify(base, incidents)

    assert completed.returncode == 1
    document = report(completed)
    assert document["recovered"] is False
    assert checks(document)["alert_absent"] is False
    assert checks(document)["impact_below_threshold"] is True


def test_an_impact_series_above_the_threshold_is_not_recovery(tmp_path: Path) -> None:
    incidents = write_incident(tmp_path)
    with fake_stack(healthy_routes(query_result=[{"metric": {}, "value": [1, "1"]}])) as base:
        completed = verify(base, incidents)

    assert completed.returncode == 1
    document = report(completed)
    assert checks(document)["impact_below_threshold"] is False


def test_a_sick_app_is_not_recovery(tmp_path: Path) -> None:
    incidents = write_incident(tmp_path)
    routes = healthy_routes()
    routes["/healthz"] = (500, {"detail": "db down"})
    routes["/api/invariants"] = (200, {"ok": False, "violations": [{"rule": "I2"}]})
    with fake_stack(routes) as base:
        completed = verify(base, incidents)

    assert completed.returncode == 1
    document = report(completed)
    assert checks(document)["app_healthz"] is False
    assert checks(document)["app_invariants"] is False
    assert checks(document)["alert_absent"] is True


def test_an_unreachable_prometheus_is_not_recovery(tmp_path: Path) -> None:
    incidents = write_incident(tmp_path)
    with fake_stack({}) as base:
        completed = verify(base, incidents, app_url="http://127.0.0.1:1")

    assert completed.returncode == 1
    document = report(completed)
    assert checks(document)["alert_absent"] is False
    assert checks(document)["impact_below_threshold"] is False
    assert document["recovered"] is False


def test_a_record_without_a_rule_expr_cannot_prove_recovery(tmp_path: Path) -> None:
    incidents = write_incident(tmp_path, expr=None)
    with fake_stack(healthy_routes()) as base:
        completed = verify(base, incidents)

    assert completed.returncode == 1
    assert checks(report(completed))["impact_below_threshold"] is False


def test_a_missing_incident_is_a_usage_error(tmp_path: Path) -> None:
    incidents = tmp_path / "incidents"
    incidents.mkdir()
    with fake_stack(healthy_routes()) as base:
        completed = verify(base, incidents)

    assert completed.returncode == 2
    assert report(completed)["error"] == "no incident record"


def test_the_script_requires_an_incident_id() -> None:
    completed = subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 2
    assert "verify-recovery.sh <incident-id>" in completed.stderr


def test_the_skill_and_the_script_agree_on_the_path() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "on-call-engineer/verify-recovery.sh <incident-id>" in skill
    assert "runbooks/verify-recovery.sh" not in skill
    assert SCRIPT.is_file()

    # The path written in the skill resolves inside the repo.
    cited = "on-call-engineer/verify-recovery.sh"
    assert (ROOT / cited).is_file()


@pytest.mark.parametrize("route", ["/healthz", "/api/invariants", "/api/v1/alerts"])
def test_each_missing_route_fails_the_run(tmp_path: Path, route: str) -> None:
    incidents = write_incident(tmp_path)
    routes = healthy_routes()
    del routes[route]
    with fake_stack(routes) as base:
        completed = verify(base, incidents)

    assert completed.returncode == 1
    assert report(completed)["recovered"] is False
