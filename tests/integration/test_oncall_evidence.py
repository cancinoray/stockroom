"""The evidence packet against a real ``/api/invariants`` and a disposable Postgres (#61).

The alert API is the same fake used by the unit suite; the app is the real
FastAPI application, pointed at the disposable database from
``tests/integration/conftest.py``, and reached through an ``httpx`` transport so
the collector's real GET path is exercised without a network listener.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
ONCALL_DIR = ROOT / "on-call-engineer"
if str(ONCALL_DIR) not in sys.path:
    sys.path.insert(0, str(ONCALL_DIR))

import collect_evidence  # noqa: E402
import packet  # noqa: E402
from config import Config  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.main import app  # noqa: E402

FIXED_NOW = 1_800_000_000

LABELS = {
    "alertname": "StockroomOrderErrorRateHigh",
    "severity": "critical",
    "service": "stockroom",
    "environment": "development",
    "version": "abc1234def",
    "owner": "stockroom-on-call",
    "dashboard_url": "http://localhost:3000/d/stockroom-order-journey",
}

ANNOTATIONS = {
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


@pytest.fixture
def real_app_client(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("STOCKROOM_DATABASE_URL", migrated_database)
    monkeypatch.setenv("STOCKROOM_COMMIT", "abc1234def")
    monkeypatch.setenv("STOCKROOM_BUILD_TIME", "2026-11-07T00:00:00Z")
    monkeypatch.setenv("STOCKROOM_ENVIRONMENT", "development")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


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


def make_client(real_app_client: TestClient) -> httpx.Client:
    """Route the app host to the real app, and Prometheus/Loki to fixed fixtures."""

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.port == 8000:
            response = real_app_client.get(path)
            return httpx.Response(
                response.status_code,
                content=response.content,
                headers={"content-type": response.headers.get("content-type", "application/json")},
            )
        if path == "/api/v1/alerts":
            return httpx.Response(200, json={"status": "success", "data": {"alerts": []}})
        if path == "/api/v1/rules":
            return httpx.Response(
                200,
                json={"status": "success", "data": {"groups": [{"name": "g", "rules": [RULE]}]}},
            )
        if path == "/api/v1/query":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"resultType": "vector", "result": []},
                },
            )
        if path == "/loki/api/v1/query_range":
            return httpx.Response(
                200,
                json={"status": "success", "data": {"resultType": "streams", "result": []}},
            )
        return httpx.Response(404, json={"error": "not found"})

    return httpx.Client(transport=httpx.MockTransport(handle), timeout=5.0)


def build(config: Config, client: httpx.Client) -> dict[str, Any]:
    alert = {
        "labels": dict(LABELS),
        "annotations": dict(ANNOTATIONS),
        "state": "firing",
        "activeAt": "2026-11-06T19:22:21Z",
        "value": "1",
    }
    collector = collect_evidence.Collector(config, clock=lambda: float(FIXED_NOW), client=client)
    observations = collector.collect(alert, FIXED_NOW)
    rules = collector.fetch_rules()
    return packet.build_packet(
        alert, rules.get(LABELS["alertname"]), observations, config, FIXED_NOW
    )


def test_real_invariants_endpoint_feeds_the_packet(
    config: Config, real_app_client: TestClient
) -> None:
    document = build(config, make_client(real_app_client))

    observations = document["observations"]
    assert observations["app"]["healthz"]["status"] == "ok"
    assert observations["app"]["healthz"]["http_status"] == 200
    assert observations["app"]["healthz"]["result"] == {"status": "ok", "db": "ok"}
    assert observations["app"]["version"]["result"]["commit"] == "abc1234def"
    assert observations["app"]["invariants"]["status"] == "ok"
    assert observations["app"]["invariants"]["http_status"] == 200
    assert observations["app"]["invariants"]["result"] == {"ok": True, "violations": []}
    assert document["service"]["deployed_version"] == "abc1234def"
    assert document["service"]["owner"] == "stockroom-on-call"


def test_same_inputs_and_clock_are_byte_identical_against_the_real_database(
    config: Config, real_app_client: TestClient
) -> None:
    first = packet.render(build(config, make_client(real_app_client)))
    second = packet.render(build(config, make_client(real_app_client)))

    assert first == second
    assert first.endswith(b"}\n")
    assert json.loads(first)["observations"]["app"]["invariants"]["result"] == {
        "ok": True,
        "violations": [],
    }
