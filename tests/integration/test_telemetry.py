"""The order journey's telemetry (T6.1 / #55), proved against a real database.

Every test runs the real app in-process against a fresh migrated, seeded
Postgres, with ``InMemorySpanExporter``, ``InMemoryMetricReader`` and a captured
log stream standing in for a collector. Nothing here needs Grafana, a collector
or external network.

Covers AC1 (span shape, parents, attributes), AC2 (one trace id across span,
logs, exemplar and problem body), AC3 (JSON lines), AC4 (sentinel sweep),
AC5 (the five metrics and their labels), AC6 (the drift gauge), AC7 (resource
attributes on all three signals) and AC8/AC9 (fail-open export).
"""

from __future__ import annotations

import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from sqlalchemy import create_engine, text

from backend import telemetry
from backend.config import get_settings
from backend.db import seed as seed_module
from backend.main import create_app
from tests.integration.test_seed import _fresh_database, _run_alembic

_REQUIRED_LOG_FIELDS = {
    "timestamp",
    "level",
    "logger",
    "message",
    "service",
    "service_version",
    "environment",
    "trace_id",
    "span_id",
}
_REQUEST_FIELDS = {"method", "route", "status_code", "duration_ms"}
_HEX_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVER_START_TIMEOUT_SECONDS = 30.0
_TEST_COMMIT = "abc1234def"
_TEST_ENVIRONMENT = "test"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@contextmanager
def _seeded_database(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A fresh, migrated, seeded database that no other test shares."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        seed_module.seed(engine)
        monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
        get_settings.cache_clear()
        try:
            yield engine
        finally:
            get_settings.cache_clear()
            engine.dispose()


@contextmanager
def _running_stack(
    engine: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: str = _TEST_ENVIRONMENT,
    commit: str = _TEST_COMMIT,
    drift_interval_seconds: float = 30.0,
    otlp_endpoint: str | None = None,
    otlp_headers: str | None = None,
    collectors: bool = True,
) -> Iterator[SimpleNamespace]:
    """A real app configured from the environment, with in-memory collectors.

    The OTLP variables are set the way T6.2 will set them per stack, so these
    tests prove the documented names rather than a Python-only shortcut.
    """
    telemetry.reset_telemetry()
    monkeypatch.setenv("STOCKROOM_ENVIRONMENT", environment)
    monkeypatch.setenv("STOCKROOM_COMMIT", commit)
    monkeypatch.setenv("STOCKROOM_TELEMETRY_DRIFT_INTERVAL_SECONDS", str(drift_interval_seconds))
    for name in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS"):
        monkeypatch.delenv(name, raising=False)
    if otlp_endpoint is not None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", otlp_endpoint)
    if otlp_headers is not None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", otlp_headers)
    get_settings.cache_clear()

    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    log_stream = io.StringIO()
    configured = telemetry.configure(
        get_settings(),
        span_exporter=span_exporter if collectors else None,
        metric_reader=metric_reader if collectors else None,
        log_stream=log_stream,
    )
    app = create_app()
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(
                client=client,
                engine=engine,
                spans=span_exporter,
                metrics=metric_reader,
                logs=log_stream,
                telemetry=configured,
            )
    finally:
        telemetry.reset_telemetry()
        configured.shutdown()


@pytest.fixture()
def stack(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """A seeded database and an instrumented app, one per test."""
    with (
        _seeded_database(database_url, monkeypatch) as engine,
        _running_stack(engine, monkeypatch) as running,
    ):
        yield running


@pytest.fixture()
def drift_stack(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """The same stack, with the drift check on a test-sized interval."""
    with (
        _seeded_database(database_url, monkeypatch) as engine,
        _running_stack(engine, monkeypatch, drift_interval_seconds=0.05) as running,
    ):
        yield running


def _place_order(
    stack: SimpleNamespace,
    *,
    sku: str = "SKU-1042",
    qty: int = 1,
    customer_ref: str = "CUST-88",
    **kwargs: Any,
) -> Any:
    return stack.client.post(
        "/api/orders",
        json={"customer_ref": customer_ref, "lines": [{"sku": sku, "qty": qty}]},
        **kwargs,
    )


def _server_span(stack: SimpleNamespace, name: str) -> Any:
    matches = [span for span in stack.spans.get_finished_spans() if span.name == name]
    assert len(matches) == 1, [span.name for span in stack.spans.get_finished_spans()]
    span = matches[0]
    assert span.kind == SpanKind.SERVER
    return span


def _trace_id(span: Any) -> str:
    return format(span.get_span_context().trace_id, "032x")


def _log_records(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _request_record(records: list[dict[str, Any]], route: str) -> dict[str, Any]:
    matches = [record for record in records if record.get("route") == route]
    assert matches, [record.get("message") for record in records]
    return matches[-1]


def _metrics(reader: InMemoryMetricReader) -> dict[str, Any]:
    data = reader.get_metrics_data()
    metrics: dict[str, Any] = {}
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                metrics[metric.name] = metric
    return metrics


def _counter_by_reason(metric: Any) -> dict[str, float]:
    return {
        str(data_point.attributes.get("reason")): data_point.value
        for data_point in metric.data.data_points
    }


def _drift_value(reader: InMemoryMetricReader) -> float | None:
    metric = _metrics(reader).get(telemetry.STOCK_DRIFT_METRIC)
    if metric is None:
        return None
    points = metric.data.data_points
    assert len(points) == 1
    return points[0].value


def _wait_for_drift(reader: InMemoryMetricReader, expected: float, timeout: float = 5.0) -> float:
    deadline = time.monotonic() + timeout
    observed: float | None = None
    while time.monotonic() < deadline:
        observed = _drift_value(reader)
        if observed == expected:
            return observed
        time.sleep(0.02)
    raise AssertionError(f"drift gauge stayed at {observed!r}, expected {expected!r}")


def _corrupt_stock_cache(engine: Any, sku: str, delta: int = 3) -> None:
    """Corrupt one cache row the way ``_docs/domain.md`` §2 lets an admin.

    The documented dedicated ``admin`` role is not implemented in this repo (no
    migration grants it), so this test helper is the stand-in: a separate
    admin-style connection writing the cache directly. It is a test seam, not a
    production mutation path. Recorded as a doc-ahead-of-code gap in the PR.
    """
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE stock SET on_hand = on_hand + :delta WHERE sku = :sku"),
            {"delta": delta, "sku": sku},
        )


def _repair_stock_cache(engine: Any, sku: str) -> None:
    """Put the cache back to the ledger's truth, as the admin repair would."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE stock s SET on_hand = ("
                "  SELECT COALESCE(SUM(m.delta_on_hand), 0)"
                "    FROM movements m"
                "   WHERE m.warehouse_id = s.warehouse_id AND m.sku = s.sku"
                ") WHERE s.sku = :sku"
            ),
            {"sku": sku},
        )


def _idle_in_transaction(engine: Any) -> list[str]:
    with engine.connect() as connection:
        states = connection.execute(
            text(
                "SELECT state FROM pg_stat_activity"
                " WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        ).scalars()
        return [state for state in states if state == "idle in transaction"]


# ---------------------------------------------------------------------------
# AC1 — the journey is traced end to end
# ---------------------------------------------------------------------------


def test_place_order_is_one_server_span_with_database_children(stack: SimpleNamespace) -> None:
    response = _place_order(stack)
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    span = _server_span(stack, "POST /api/orders")

    assert span.attributes["http.request.method"] == "POST"
    assert span.attributes["http.route"] == "/api/orders"
    assert span.attributes["http.response.status_code"] == 201
    assert span.attributes["order.id"] == order_id

    finished = stack.spans.get_finished_spans()
    children = [
        other for other in finished if other.parent and other.parent.span_id == span.context.span_id
    ]
    assert children, "the reservation transaction left no child span"
    assert all(child.kind == SpanKind.CLIENT for child in children)
    assert {child.attributes["db.operation"] for child in children} >= {"SELECT", "INSERT"}
    for child in children:
        assert span.start_time <= child.start_time
        assert child.end_time <= span.end_time

    # No orphan spans: the request's server span and its children, nothing else.
    for finished_span in finished:
        assert finished_span is span or (
            finished_span.parent is not None
            and finished_span.parent.span_id == span.context.span_id
        )


def test_cancel_and_fulfil_have_the_same_span_shape(stack: SimpleNamespace) -> None:
    place = _place_order(stack)
    assert place.status_code == 201
    order_id = place.json()["id"]

    cancel = stack.client.post(f"/api/orders/{order_id}/cancel")
    assert cancel.status_code == 200, cancel.text
    cancel_span = _server_span(stack, "POST /api/orders/{id}/cancel")
    assert cancel_span.attributes["http.route"] == "/api/orders/{id}/cancel"
    assert cancel_span.attributes["http.response.status_code"] == 200
    assert cancel_span.attributes["order.id"] == order_id

    second = _place_order(stack)
    assert second.status_code == 201
    fulfil = stack.client.post(f"/api/orders/{second.json()['id']}/fulfil")
    assert fulfil.status_code == 200, fulfil.text
    fulfil_span = _server_span(stack, "POST /api/orders/{id}/fulfil")
    assert fulfil_span.attributes["http.route"] == "/api/orders/{id}/fulfil"
    assert fulfil_span.attributes["http.response.status_code"] == 200
    assert fulfil_span.attributes["order.id"] == second.json()["id"]

    for span in (cancel_span, fulfil_span):
        children = [
            other
            for other in stack.spans.get_finished_spans()
            if other.parent and other.parent.span_id == span.context.span_id
        ]
        assert children
        assert span.status.status_code != StatusCode.ERROR


def test_insufficient_stock_is_an_error_span_with_the_problem_type(
    stack: SimpleNamespace,
) -> None:
    response = _place_order(stack, sku="SKU-8820", qty=99)

    assert response.status_code == 409
    assert response.json()["type"] == "insufficient_stock"

    span = _server_span(stack, "POST /api/orders")

    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == "insufficient_stock"
    assert span.attributes["error.type"] == "insufficient_stock"
    assert span.attributes["http.response.status_code"] == 409
    assert "order.id" not in span.attributes
    # A rejection is not a crash: no exception event, no stack trace.
    assert [event for event in span.events if event.name == "exception"] == []


def test_invalid_transition_is_an_error_span_with_the_problem_type(
    stack: SimpleNamespace,
) -> None:
    place = _place_order(stack)
    order_id = place.json()["id"]
    assert stack.client.post(f"/api/orders/{order_id}/fulfil").status_code == 200

    response = stack.client.post(f"/api/orders/{order_id}/cancel")

    assert response.status_code == 409
    assert response.json()["type"] == "invalid_transition"
    span = _server_span(stack, "POST /api/orders/{id}/cancel")
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "invalid_transition"
    assert span.attributes["order.id"] == order_id


# ---------------------------------------------------------------------------
# AC2 — one trace id, not two
# ---------------------------------------------------------------------------


def test_one_trace_id_across_span_logs_and_the_metric_exemplar(stack: SimpleNamespace) -> None:
    response = _place_order(stack)
    assert response.status_code == 201

    trace_id = _trace_id(_server_span(stack, "POST /api/orders"))
    assert _HEX_TRACE_ID.match(trace_id)

    request_records = [
        record for record in _log_records(stack.logs) if record.get("route") == "/api/orders"
    ]
    assert request_records
    assert {record["trace_id"] for record in request_records} == {trace_id}

    metric = _metrics(stack.metrics)[telemetry.REQUEST_DURATION_METRIC]
    sample = next(
        data_point
        for data_point in metric.data.data_points
        if data_point.attributes["http.route"] == "/api/orders"
    )
    assert sample.exemplars
    assert [format(exemplar.trace_id, "032x") for exemplar in sample.exemplars] == [trace_id]


def test_problem_body_trace_id_is_the_request_span_trace_id(stack: SimpleNamespace) -> None:
    response = _place_order(stack, sku="SKU-8820", qty=99)

    assert response.status_code == 409
    body = response.json()
    span = _server_span(stack, "POST /api/orders")
    trace_id = _trace_id(span)

    assert body["trace_id"] == trace_id
    request_records = [
        record for record in _log_records(stack.logs) if record.get("route") == "/api/orders"
    ]
    assert request_records
    assert {record["trace_id"] for record in request_records} == {trace_id}
    assert {_trace_id(other) for other in stack.spans.get_finished_spans()} == {trace_id}


# ---------------------------------------------------------------------------
# AC3 — JSON logs with the fixed field set
# ---------------------------------------------------------------------------


def test_every_line_written_for_a_request_is_one_json_object(stack: SimpleNamespace) -> None:
    assert _place_order(stack).status_code == 201

    raw_lines = [line for line in stack.logs.getvalue().splitlines() if line.strip()]
    assert raw_lines

    payloads = [json.loads(line) for line in raw_lines]
    for payload in payloads:
        assert set(payload) >= _REQUIRED_LOG_FIELDS
        assert payload["service"] == "stockroom"
        assert payload["service_version"] == _TEST_COMMIT
        assert payload["environment"] == _TEST_ENVIRONMENT
        assert payload["timestamp"].endswith("Z")

    request = _request_record(payloads, "/api/orders")
    assert set(request) >= _REQUEST_FIELDS
    assert request["method"] == "POST"
    assert request["status_code"] == 201
    assert isinstance(request["duration_ms"], (int, float))
    assert request["message"] == "POST /api/orders 201"


# ---------------------------------------------------------------------------
# AC4 — no PII or secret reaches any signal
# ---------------------------------------------------------------------------


def test_no_sentinel_reaches_spans_logs_metrics_or_exemplars(stack: SimpleNamespace) -> None:
    # Composed at run time so no literal in this file looks like a real
    # credential to a secret scanner while the sweep still has a unique value.
    sentinels = {
        "name": "Ada Sentinel Lovelace",
        "email": "ada.sentinel@example.com",
        "token": "sentinel-" + "bearer-8f3c2a",
        "api_key": "sentinel-" + "api-key-55aa",
        "dsn": "".join(
            (
                "postgresql://",
                "sentinel_reader:",
                "not-a-real-password",
                "@db.sentinel:5432/sentinel",
            )
        ),
    }
    response = stack.client.post(
        "/api/orders",
        params={"api_key": sentinels["api_key"], "dsn": sentinels["dsn"]},
        headers={
            "Authorization": "Bearer " + sentinels["token"],
            "X-Api-Key": sentinels["api_key"],
            "User-Agent": sentinels["name"],
        },
        json={
            "customer_ref": "CUST-88",
            "name": sentinels["name"],
            "email": sentinels["email"],
            "lines": [{"sku": "SKU-1042", "qty": 1}],
        },
    )
    assert response.status_code == 201, response.text

    haystack: list[str] = [stack.logs.getvalue()]
    for span in stack.spans.get_finished_spans():
        haystack.append(
            json.dumps({key: str(value) for key, value in (span.attributes or {}).items()})
        )
        for event in span.events:
            haystack.append(
                json.dumps({key: str(value) for key, value in (event.attributes or {}).items()})
            )

    for metric in _metrics(stack.metrics).values():
        for data_point in metric.data.data_points:
            haystack.append(
                json.dumps({key: str(value) for key, value in data_point.attributes.items()})
            )
            for exemplar in getattr(data_point, "exemplars", ()):
                haystack.append(
                    json.dumps(
                        {
                            key: str(value)
                            for key, value in (exemplar.filtered_attributes or {}).items()
                        }
                    )
                )

    everything = "\n".join(haystack)
    for label, sentinel in sentinels.items():
        assert sentinel not in everything, f"{label} leaked into telemetry"

    # customer_ref is allowed in logs but never a metric label.
    for metric in _metrics(stack.metrics).values():
        for data_point in metric.data.data_points:
            assert {
                "order_id",
                "customer_ref",
                "trace_id",
            }.isdisjoint(data_point.attributes)


def test_a_sentinel_path_segment_never_becomes_an_order_id(stack: SimpleNamespace) -> None:
    sentinel = "sentinel-order-id-9f3d"

    response = stack.client.post(f"/api/orders/{sentinel}/cancel")

    assert response.status_code == 404
    span = _server_span(stack, "POST /api/orders/{id}/cancel")
    assert "order.id" not in span.attributes
    assert sentinel not in json.dumps({key: str(value) for key, value in span.attributes.items()})
    assert sentinel not in stack.logs.getvalue()


# ---------------------------------------------------------------------------
# AC5 — five metrics with bounded labels
# ---------------------------------------------------------------------------


def test_five_metrics_with_the_stated_deltas_and_bounded_labels(stack: SimpleNamespace) -> None:
    placed = _place_order(stack)
    assert placed.status_code == 201
    order_id = placed.json()["id"]
    assert stack.client.post(f"/api/orders/{order_id}/fulfil").status_code == 200
    invalid = stack.client.post(f"/api/orders/{order_id}/cancel")
    assert invalid.status_code == 409
    rejected = _place_order(stack, sku="SKU-8820", qty=99)
    assert rejected.status_code == 409

    metrics = _metrics(stack.metrics)

    assert set(metrics) == {
        telemetry.ORDERS_PLACED_METRIC,
        telemetry.ORDERS_FAILED_METRIC,
        telemetry.REQUEST_DURATION_METRIC,
        telemetry.RESERVATION_CONFLICTS_METRIC,
        telemetry.STOCK_DRIFT_METRIC,
    }

    placed_points = metrics[telemetry.ORDERS_PLACED_METRIC].data.data_points
    assert len(placed_points) == 1
    assert placed_points[0].value == 1

    assert _counter_by_reason(metrics[telemetry.ORDERS_FAILED_METRIC]) == {
        "invalid_transition": 1,
        "insufficient_stock": 1,
    }
    assert _counter_by_reason(metrics[telemetry.RESERVATION_CONFLICTS_METRIC]) == {
        "insufficient_stock": 1
    }

    duration = metrics[telemetry.REQUEST_DURATION_METRIC].data.data_points
    assert sum(data_point.count for data_point in duration) == 4
    assert duration[0].explicit_bounds == telemetry.REQUEST_DURATION_BUCKETS_SECONDS

    assert _drift_value(stack.metrics) == 0

    allowed_labels = {
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "reason",
    }
    for metric in metrics.values():
        for data_point in metric.data.data_points:
            assert set(data_point.attributes) <= allowed_labels
            route = data_point.attributes.get("http.route")
            if route is not None:
                assert "?" not in route
                assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", route)
            reason = data_point.attributes.get("reason")
            if reason is not None:
                assert reason in {"insufficient_stock", "invalid_transition"}


# ---------------------------------------------------------------------------
# AC6 — the drift gauge tracks the truth
# ---------------------------------------------------------------------------


def test_drift_gauge_is_zero_on_a_seeded_database(drift_stack: SimpleNamespace) -> None:
    assert _drift_value(drift_stack.metrics) == 0


def test_drift_gauge_rises_with_a_corrupted_cache_and_returns_to_zero(
    drift_stack: SimpleNamespace,
) -> None:
    assert _drift_value(drift_stack.metrics) == 0

    _corrupt_stock_cache(drift_stack.engine, "SKU-1042", delta=3)

    assert _wait_for_drift(drift_stack.metrics, 1) == 1

    warnings = [
        record
        for record in _log_records(drift_stack.logs)
        if record["level"] == "WARNING" and "drift" in record["message"].lower()
    ]
    assert warnings, _log_records(drift_stack.logs)
    # The rule id and the SKU, and nothing about the row's numbers or a customer.
    assert warnings[-1]["message"] == "Stock invariant drift detected (rule=I2, sku=SKU-1042)"

    # The check holds no transaction, and a stock write still goes through.
    assert _idle_in_transaction(drift_stack.engine) == []
    receive = drift_stack.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": 1, "note": "drift probe"},
    )
    assert receive.status_code == 201, receive.text

    _repair_stock_cache(drift_stack.engine, "SKU-1042")

    assert _wait_for_drift(drift_stack.metrics, 0) == 0


# ---------------------------------------------------------------------------
# AC7 — resource attributes on all three signals
# ---------------------------------------------------------------------------


def test_resource_attributes_reach_spans_logs_and_metrics(stack: SimpleNamespace) -> None:
    assert _place_order(stack).status_code == 201

    version = stack.client.get("/api/version").json()
    assert version["commit"] == _TEST_COMMIT

    span = _server_span(stack, "POST /api/orders")
    resource = dict(span.resource.attributes)
    assert resource["service.name"] == "stockroom"
    assert resource["service.version"] == version["commit"]
    assert resource["deployment.environment"] == _TEST_ENVIRONMENT

    request = _request_record(_log_records(stack.logs), "/api/orders")
    assert request["service"] == "stockroom"
    assert request["service_version"] == version["commit"]
    assert request["environment"] == _TEST_ENVIRONMENT

    exported = stack.metrics.get_metrics_data()
    assert exported.resource_metrics
    for resource_metrics in exported.resource_metrics:
        attributes = dict(resource_metrics.resource.attributes)
        assert attributes["service.name"] == "stockroom"
        assert attributes["service.version"] == version["commit"]
        assert attributes["deployment.environment"] == _TEST_ENVIRONMENT


def test_changing_the_environment_changes_the_exported_logs(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (
        _seeded_database(database_url, monkeypatch) as engine,
        _running_stack(engine, monkeypatch, environment="staging") as staging,
    ):
        assert _place_order(staging).status_code == 201
        request = _request_record(_log_records(staging.logs), "/api/orders")
        assert request["environment"] == "staging"
        span = _server_span(staging, "POST /api/orders")
        assert dict(span.resource.attributes)["deployment.environment"] == "staging"


# ---------------------------------------------------------------------------
# AC8 / AC9 — fail-open offline export and credential redaction
# ---------------------------------------------------------------------------


def test_without_an_endpoint_the_app_runs_and_exports_nothing(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (
        _seeded_database(database_url, monkeypatch) as engine,
        _running_stack(engine, monkeypatch, collectors=False) as silent,
    ):
        assert silent.telemetry.exporting is False
        assert silent.telemetry.span_exporter is None

        assert silent.client.get("/healthz").status_code == 200
        assert _place_order(silent).status_code == 201

        payloads = _log_records(silent.logs)
        assert payloads
        # Fail-open: no exporter, and no warning per request.
        assert [record for record in payloads if record["level"] in {"WARNING", "ERROR"}] == []


def test_a_closed_export_port_keeps_requests_fast_and_logs_one_redacted_line(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Composed at run time; the value only has to be unique for the sweep.
    secret = "Bearer " + "export-credential-9f1c7d"
    endpoint = "http://127.0.0.1:1"
    with (
        _seeded_database(database_url, monkeypatch) as engine,
        _running_stack(
            engine,
            monkeypatch,
            otlp_endpoint=endpoint,
            otlp_headers=f"authorization={secret}",
            collectors=False,
        ) as failing,
    ):
        assert failing.telemetry.exporting is True

        started = time.perf_counter()
        response = _place_order(failing)
        elapsed = time.perf_counter() - started
        assert response.status_code == 201, response.text
        assert elapsed < 2.0

        # The batch processor exports off the request path; force both signals
        # so the failure path is exercised twice.
        failing.telemetry.force_flush()
        failing.telemetry.force_flush()

        lines = [line for line in failing.logs.getvalue().splitlines() if line.strip()]
        payloads = [json.loads(line) for line in lines]
        failures = [
            payload for payload in payloads if "export failed" in payload["message"].lower()
        ]
        assert len(failures) == 1
        assert all(secret not in line for line in lines)
        assert all(endpoint not in line for line in lines)


# ---------------------------------------------------------------------------
# AC3, the uvicorn half — a real server process, not just the in-process app
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_ready(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + _SERVER_START_TIMEOUT_SECONDS
    with httpx.Client(trust_env=False, timeout=2.0) as http:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError("uvicorn exited before becoming ready")
            try:
                if http.get(f"http://127.0.0.1:{port}/healthz").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    raise AssertionError(f"uvicorn did not answer /healthz within {_SERVER_START_TIMEOUT_SECONDS}s")


def test_a_live_uvicorn_writes_one_json_object_per_line(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The startup and access lines uvicorn writes are JSON too (AC3).

    A subprocess so uvicorn's own logging configuration is in play; interpreter
    deprecation warnings from Starlette are suppressed because they are not app
    log records and would otherwise be stderr noise in this check.
    """
    with _seeded_database(database_url, monkeypatch) as engine:
        port = _free_port()
        handle, log_name = tempfile.mkstemp(prefix="stockroom-telemetry-", suffix=".log")
        log_path = Path(log_name)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS"}
        }
        environment["PYTHONWARNINGS"] = "ignore"
        with os.fdopen(handle, "w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "backend.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "info",
                ],
                cwd=REPO_ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        try:
            _wait_until_ready(port, process)
            with httpx.Client(trust_env=False, timeout=10.0) as http:
                response = http.post(
                    f"http://127.0.0.1:{port}/api/orders",
                    json={
                        "customer_ref": "CUST-88",
                        "lines": [{"sku": "SKU-1042", "qty": 1}],
                    },
                )
            assert response.status_code == 201, response.text
        finally:
            process.terminate()
            process.wait(timeout=20)

        output = log_path.read_text(encoding="utf-8", errors="replace")
        log_path.unlink(missing_ok=True)
        engine.dispose()

    lines = [line for line in output.splitlines() if line.strip()]
    assert lines

    payloads = [json.loads(line) for line in lines]
    for payload in payloads:
        assert set(payload) >= _REQUIRED_LOG_FIELDS
        assert payload["service"] == "stockroom"

    access = [
        payload
        for payload in payloads
        if payload["logger"] == "uvicorn.access" and "POST /api/orders" in payload["message"]
    ]
    assert access
    assert access[0]["status_code"] == 201
    assert access[0]["trace_id"]
    # The formatter rebuilds the access line without the caller's address.
    assert "127.0.0.1" not in json.dumps(access[0])
