"""The evidence collector: allowlisted reads, a frozen packet contract and no PII (#61).

Every test uses a fake Prometheus/Loki/app HTTP fixture, a frozen clock and a
temporary directory. Nothing here touches a container or the network.
"""

from __future__ import annotations

import ast
import json
import re
import socket
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ONCALL_DIR = ROOT / "on-call-engineer"
if str(ONCALL_DIR) not in sys.path:
    sys.path.insert(0, str(ONCALL_DIR))

import collect_evidence  # noqa: E402
import packet  # noqa: E402
from config import Config  # noqa: E402

FIXED_NOW = 1_800_000_000

BASE_LABELS = {
    "alertname": "StockroomOrderErrorRateHigh",
    "severity": "critical",
    "service": "stockroom",
    "environment": "development",
    "version": "abc1234def",
    "owner": "stockroom-on-call",
    "dashboard_url": "http://localhost:3000/d/stockroom-order-journey",
    "instance": "otel-collector:8889",
    "job": "otel-collector",
}

BASE_ANNOTATIONS = {
    "summary": "Order journey is returning 5xx above 5%",
    "description": "1 of 1 order-journey requests failed.",
    "runbook_url": "_docs/runbooks/stockroom-order-error-rate-high.md",
}

RULE = {
    "name": "StockroomOrderErrorRateHigh",
    "query": "(sum(rate(stockroom_http_request_duration_seconds_count[5m]))) > 0.05",
    "for": "1m",
    "type": "alerting",
    "state": "firing",
    "labels": {},
    "annotations": {},
}

TRACE_A = "a" * 32
TRACE_B = "b" * 32
TRACE_C = "c" * 32

FORBIDDEN_KEYS = {
    "authorization",
    "cookie",
    "customer_ref",
    "customer_name",
    "email",
    "password",
    "token",
    "database_url",
    "otel_exporter_otlp_headers",
    "headers",
    "body",
}


class FakeApi:
    def __init__(
        self,
        *,
        alerts: list[dict[str, Any]] | None = None,
        rules: list[dict[str, Any]] | None = None,
        prometheus_result: Any = None,
        loki: dict[str, Any] | None = None,
        app: dict[str, tuple[int, Any]] | None = None,
    ) -> None:
        self.alerts = [make_alert()] if alerts is None else alerts
        self.rules = [RULE] if rules is None else rules
        self.prometheus_result = (
            {"resultType": "vector", "result": [{"metric": {}, "value": [FIXED_NOW, "0.42"]}]}
            if prometheus_result is None
            else prometheus_result
        )
        self.loki = default_loki() if loki is None else loki
        self.app = default_app() if app is None else app
        self.failure: str | None = None
        self.failure_kind = "connect"
        self.failure_body: Any = None
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=5.0)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.failure and self._fails(path):
            if self.failure_kind == "connect":
                raise httpx.ConnectError("failed http://operator:secret@upstream.invalid")
            return httpx.Response(500, json=self.failure_body or {"error": "unavailable"})

        if path == "/api/v1/alerts":
            return _json({"status": "success", "data": {"alerts": self.alerts}})
        if path == "/api/v1/rules":
            return _json(
                {"status": "success", "data": {"groups": [{"name": "g", "rules": self.rules}]}}
            )
        if path == "/api/v1/query":
            return _json({"status": "success", "data": self.prometheus_result})
        if path == "/loki/api/v1/query_range":
            return _json(self.loki)
        if path in self.app:
            status, body = self.app[path]
            return _json(body, status=status)
        return _json({"error": "not found"}, status=404)

    def _fails(self, path: str) -> bool:
        return {
            "alerts": path == "/api/v1/alerts",
            "rules": path == "/api/v1/rules",
            "query": path == "/api/v1/query",
            "loki": path == "/loki/api/v1/query_range",
            "app": path in self.app,
        }.get(self.failure or "", False)

    def queries(self) -> list[str]:
        return [
            request.url.params["query"]
            for request in self.requests
            if request.url.path == "/api/v1/query"
        ]


def _json(body: Any, *, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def make_alert(
    *,
    labels: dict[str, Any] | None = None,
    annotations: dict[str, Any] | None = None,
    state: str = "firing",
) -> dict[str, Any]:
    merged = dict(BASE_LABELS)
    for key, value in (labels or {}).items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return {
        "labels": merged,
        "annotations": dict(BASE_ANNOTATIONS) if annotations is None else annotations,
        "state": state,
        "activeAt": "2026-11-06T19:22:21Z",
        "value": "1",
    }


def _log_line(trace_id: str, status_code: int, **extra: Any) -> dict[str, Any]:
    return {
        "timestamp": "2026-11-07T09:59:59.000Z",
        "level": "ERROR",
        "message": f"POST /api/orders HTTP/1.1 {status_code}",
        "method": "POST",
        "route": "/api/orders",
        "status_code": status_code,
        "duration_ms": 3.2,
        "trace_id": trace_id,
        **extra,
    }


def default_loki() -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"container": "stockroom-app-1"},
                    "values": [
                        [f"{FIXED_NOW}000000000", json.dumps(_log_line(TRACE_A, 500))],
                        [f"{FIXED_NOW - 1}000000000", json.dumps(_log_line(TRACE_B, 500))],
                    ],
                }
            ],
        },
    }


def default_app() -> dict[str, tuple[int, Any]]:
    return {
        "/healthz": (200, {"status": "ok", "db": "ok"}),
        "/api/version": (
            200,
            {
                "version": "0.1.0",
                "commit": "abc1234def",
                "build_time": "2026-11-07T00:00:00Z",
                "environment": "development",
            },
        ),
        "/api/invariants": (200, {"ok": True, "violations": []}),
    }


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        prometheus_url="http://127.0.0.1:9090",
        loki_url="http://127.0.0.1:3100",
        app_url="http://127.0.0.1:8000",
        poll_interval_seconds=60,
        lookback_minutes=15,
        log_samples=20,
        trace_samples=3,
        http_timeout_seconds=5.0,
        evidence_dir=tmp_path / "evidence",
        state_dir=tmp_path / "state",
        resolve_grace_polls=2,
        base_ref="main",
        base_commit="deadbeefcafe",
        image_reference="stockroom-app:local",
    )


def build(
    config: Config,
    fake: FakeApi,
    *,
    alert: dict[str, Any] | None = None,
    now: int = FIXED_NOW,
) -> dict[str, Any]:
    collector = collect_evidence.Collector(config, clock=lambda: float(now), client=fake.client())
    chosen = alert if alert is not None else fake.alerts[0]
    observations = collector.collect(chosen, now)
    rules = collector.fetch_rules()
    rule = rules.get(str(chosen["labels"].get("alertname")))
    return packet.build_packet(chosen, rule, observations, config, now)


def rendered(document: dict[str, Any]) -> str:
    return packet.render(document).decode("utf-8")


def test_packet_has_exactly_the_frozen_top_level_and_nested_keys(
    config: Config,
) -> None:
    document = build(config, FakeApi())

    assert set(document) == {
        "incident_id",
        "generated_at",
        "alert",
        "service",
        "deploy",
        "repo",
        "observations",
        "limits",
    }
    assert set(document["alert"]) == {
        "name",
        "severity",
        "state",
        "active_at",
        "value",
        "labels",
        "fingerprint",
        "annotations",
        "rule",
    }
    assert set(document["alert"]["rule"]) == {"expr", "for", "state"}
    assert set(document["service"]) == {
        "name",
        "environment",
        "deployed_version",
        "version_source",
        "owner",
        "dashboard_url",
        "runbook_url",
    }
    assert set(document["deploy"]) == {"image_reference", "version_label"}
    assert set(document["repo"]) == {"base_ref", "base_commit", "source"}
    assert set(document["observations"]) == {"prometheus", "logs", "app"}
    assert set(document["observations"]["logs"]) == {
        "selector",
        "status",
        "error",
        "http_status",
        "window",
        "samples",
        "trace_ids",
    }
    assert set(document["limits"]) == {
        "lookback_minutes",
        "log_samples",
        "trace_samples",
        "http_timeout_seconds",
        "resolve_grace_polls",
    }

    assert document["alert"]["name"] == "StockroomOrderErrorRateHigh"
    assert document["alert"]["severity"] == "critical"
    assert document["alert"]["state"] == "firing"
    assert document["alert"]["active_at"] == "2026-11-06T19:22:21Z"
    assert document["alert"]["fingerprint"] == packet.fingerprint(BASE_LABELS)
    assert document["alert"]["rule"] == {
        "expr": RULE["query"],
        "for": "1m",
        "state": "firing",
    }
    assert document["service"]["deployed_version"] == "abc1234def"
    assert document["service"]["version_source"] == "alert_label"
    assert document["service"]["owner"] == "stockroom-on-call"
    assert document["service"]["dashboard_url"].startswith("http://localhost:3000/")
    assert document["deploy"]["image_reference"] == "stockroom-app:local"
    assert document["deploy"]["version_label"] == "abc1234def"
    assert document["repo"] == {
        "base_ref": "main",
        "base_commit": "deadbeefcafe",
        "source": "poller_checkout",
    }
    assert document["generated_at"].endswith("Z")


def test_alert_rule_is_null_when_the_rule_is_no_longer_listed(config: Config) -> None:
    document = build(config, FakeApi(rules=[]))

    assert document["alert"]["rule"] is None


def test_rule_for_uses_prometheus_duration_when_for_is_absent() -> None:
    assert packet.rule_for({"query": "q", "for": "1m"}) == "1m"
    assert packet.rule_for({"query": "q", "duration": 60}) == "60s"
    assert packet.rule_for({"query": "q"}) is None
    assert packet.rule_for({"duration": True}) is None


def test_unknown_alert_labels_are_dropped_rather_than_copied(config: Config) -> None:
    document = build(config, FakeApi())

    assert set(document["alert"]["labels"]) <= set(packet.ALLOWED_ALERT_LABELS)
    assert "instance" not in document["alert"]["labels"]
    assert "job" not in document["alert"]["labels"]


def test_prometheus_queries_are_the_allowlisted_expressions(config: Config) -> None:
    document = build(config, FakeApi())

    assert [item["name"] for item in document["observations"]["prometheus"]] == [
        "order_error_ratio",
        "orders_placed_rate",
        "orders_failed_rate",
    ]

    rule_set = yaml.safe_load((ROOT / "observability" / "alerts.yaml").read_text(encoding="utf-8"))
    expressions = {
        rule["alert"]: re.sub(r"\s+", " ", rule["expr"]).strip()
        for group in rule_set["groups"]
        for rule in group["rules"]
    }

    for alert_name, entries in collect_evidence.PROMETHEUS_QUERIES.items():
        queries = {re.sub(r"\s+", " ", query).strip() for _, query in entries}
        value_query = re.sub(r">\s*[0-9.]+$", "", expressions[alert_name]).strip()
        assert value_query in queries
        assert any(query.startswith("sum(rate(stockroom_orders_placed_total") for query in queries)
        assert any(query.startswith("sum by (reason)") for query in queries)


def test_unknown_alert_name_records_no_prometheus_query(config: Config) -> None:
    alert = make_alert(labels={"alertname": "StockroomSomethingElse"})
    document = build(config, FakeApi(), alert=alert)

    assert document["alert"]["name"] == "StockroomSomethingElse"
    assert document["observations"]["prometheus"] == []


def test_promql_injection_in_labels_never_becomes_a_query(config: Config) -> None:
    injection = "0.05) or on() vector(1) #"
    alert = make_alert(labels={"service": injection, "version": injection, "owner": injection})
    fake = FakeApi()

    build(config, fake, alert=alert)

    queries = fake.queries()
    allowed = {
        query for entries in collect_evidence.PROMETHEUS_QUERIES.values() for _, query in entries
    }
    assert queries
    assert set(queries) <= allowed
    assert all("vector(1)" not in query for query in queries)


def test_loki_selector_is_fixed_and_bounded_by_the_configured_window(
    config: Config,
) -> None:
    config = replace(config, log_samples=2)
    alert = make_alert(labels={"alertname": "StockroomOrderLatencyP95High"})
    fake = FakeApi(alerts=[alert])
    collector = collect_evidence.Collector(
        config, clock=lambda: float(FIXED_NOW), client=fake.client()
    )

    collector.collect(alert, FIXED_NOW)

    request = next(item for item in fake.requests if item.url.path == "/loki/api/v1/query_range")
    params = request.url.params
    assert params["query"] == collect_evidence.LOKI_SELECTOR
    assert params["limit"] == "2"
    assert params["start"] == str((FIXED_NOW - 15 * 60) * 10**9)
    assert params["end"] == str(FIXED_NOW * 10**9)


def test_trace_ids_are_extracted_from_log_samples_and_capped(config: Config) -> None:
    config = replace(config, trace_samples=1)
    loki = default_loki()
    loki["data"]["result"][0]["values"].append(
        [f"{FIXED_NOW - 2}000000000", json.dumps(_log_line(TRACE_C, 500))]
    )
    fake = FakeApi(loki=loki)
    collector = collect_evidence.Collector(
        config, clock=lambda: float(FIXED_NOW), client=fake.client()
    )

    observations = collector.collect(fake.alerts[0], FIXED_NOW)

    assert observations["logs"]["status"] == "ok"
    assert observations["logs"]["trace_ids"] == [TRACE_A]
    assert len(observations["logs"]["samples"]) == 3
    assert observations["logs"]["samples"][0]["trace_id"] == TRACE_A


def test_trace_ids_prefer_the_order_journey(config: Config) -> None:
    loki = {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"container": "stockroom-app-1"},
                    "values": [
                        [
                            f"{FIXED_NOW}000000000",
                            json.dumps(_log_line(TRACE_A, 503, route="/healthz")),
                        ],
                        [f"{FIXED_NOW - 1}000000000", json.dumps(_log_line(TRACE_B, 500))],
                    ],
                }
            ],
        },
    }
    fake = FakeApi(loki=loki)
    collector = collect_evidence.Collector(
        config, clock=lambda: float(FIXED_NOW), client=fake.client()
    )

    observations = collector.collect(fake.alerts[0], FIXED_NOW)

    assert observations["logs"]["trace_ids"] == [TRACE_B, TRACE_A]


def test_app_observations_read_only_the_three_allowed_paths(config: Config) -> None:
    fake = FakeApi()
    collector = collect_evidence.Collector(
        config, clock=lambda: float(FIXED_NOW), client=fake.client()
    )

    collector.collect(fake.alerts[0], FIXED_NOW)

    app_paths = ["/healthz", "/api/version", "/api/invariants"]
    requested = [request.url.path for request in fake.requests if request.url.path in app_paths]
    assert requested == app_paths
    assert {request.method for request in fake.requests} == {"GET"}


@pytest.mark.parametrize("failure", ["query", "loki", "app"])
def test_a_failed_observation_is_unavailable_and_never_aborts_the_packet(
    config: Config, failure: str
) -> None:
    fake = FakeApi()
    fake.failure = failure
    fake.failure_kind = "connect"

    document = build(config, fake)

    assert set(document) == {
        "incident_id",
        "generated_at",
        "alert",
        "service",
        "deploy",
        "repo",
        "observations",
        "limits",
    }
    observations = document["observations"]
    if failure == "query":
        assert {item["status"] for item in observations["prometheus"]} == {"unavailable"}
        assert {item["error"] for item in observations["prometheus"]} == {"ConnectError"}
    elif failure == "loki":
        assert observations["logs"]["status"] == "unavailable"
        assert observations["logs"]["error"] == "ConnectError"
    else:
        assert {entry["status"] for entry in observations["app"].values()} == {"unavailable"}
        assert observations["app"]["healthz"]["error"] == "ConnectError"


def test_every_outbound_request_is_a_get(config: Config) -> None:
    fake = FakeApi()
    collector = collect_evidence.Collector(
        config, clock=lambda: float(FIXED_NOW), client=fake.client()
    )

    observations = collector.collect(fake.alerts[0], FIXED_NOW)
    assert set(observations["app"]) == {"healthz", "version", "invariants"}
    assert {request.method for request in fake.requests} == {"GET"}


def test_packet_denylist_rejects_secrets_customer_data_and_request_bodies(
    config: Config,
) -> None:
    forbidden_label = {
        "customer_ref": "cust-123",
        "customer_name": "Ada Lovelace",
        "email": "ada@example.com",
        "Authorization": "Bearer abc123",
        "Cookie": "session=abc",
        "password": "hunter2",
        "token": "leak-me",
        "DATABASE_URL": "postgresql://stockroom:pw@db:5432/stockroom",
        "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Basic abc",
    }
    log_line = _log_line(
        TRACE_A,
        500,
        customer_ref="cust-123",
        customer_name="Ada Lovelace",
        email="ada@example.com",
        Authorization="Bearer abc123",
        password="hunter2",
    )
    loki = {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"container": "stockroom-app-1"},
                    "values": [[f"{FIXED_NOW}000000000", json.dumps(log_line)]],
                }
            ],
        },
    }
    app = default_app()
    app["/api/version"] = (
        200,
        {
            **app["/api/version"][1],
            "token": "leak-me",
            "headers": {"Authorization": "Bearer abc123"},
            "body": {"customer_ref": "cust-123"},
        },
    )
    alert = make_alert(labels=forbidden_label)
    document = build(config, FakeApi(alerts=[alert], loki=loki, app=app), alert=alert)

    text = rendered(document)
    lowered = text.lower()
    keys = _all_keys(document)

    assert keys.isdisjoint(FORBIDDEN_KEYS)
    for value in (
        "cust-123",
        "ada@example.com",
        "hunter2",
        "leak-me",
        "bearer abc123",
        "postgresql://",
        "basic abc",
        "otel_exporter_otlp_headers",
    ):
        assert value not in lowered


def test_errors_redact_userinfo_and_do_not_copy_response_bodies(config: Config) -> None:
    fake = FakeApi()
    fake.failure = "query"
    fake.failure_kind = "status"
    fake.failure_body = {
        "error": "Authorization: Bearer abc123 postgresql://stockroom:pw@db:5432/stockroom"
    }

    document = build(config, fake)

    observations = document["observations"]["prometheus"]
    assert {item["error"] for item in observations} == {"HTTP 500"}
    text = rendered(document).lower()
    assert "bearer abc123" not in text
    assert "postgresql://" not in text
    assert "operator:secret" not in text


def test_same_inputs_and_clock_produce_byte_identical_json(config: Config) -> None:
    first = packet.render(build(config, FakeApi()))
    second = packet.render(build(config, FakeApi()))

    assert first == second
    assert first.endswith(b"}\n")
    assert not first.endswith(b"\n\n")
    assert json.loads(first) == json.loads(second)


def test_packet_has_no_machine_paths_hostnames_or_wall_clock_drift(config: Config) -> None:
    text = rendered(build(config, FakeApi()))

    assert str(config.state_dir) not in text
    assert str(config.evidence_dir) not in text
    assert "/Users/" not in text
    assert socket.gethostname() not in text
    assert "+00:00" not in text
    assert re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text) is None


def test_the_collector_imports_no_database_driver() -> None:
    forbidden = {
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "asyncpg",
        "databases",
        "pymysql",
        "mysql",
        "aiosqlite",
        "sqlite3",
    }
    imported: set[str] = set()
    for path in sorted(ONCALL_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    assert imported.isdisjoint(forbidden)
    assert "httpx" in imported


def _all_keys(document: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            keys.add(str(key).lower())
            keys.update(_all_keys(value))
    elif isinstance(document, list):
        for item in document:
            keys.update(_all_keys(item))
    return keys
