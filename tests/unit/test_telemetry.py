"""Telemetry primitives: the JSON formatter, the id bridge and the resource.

These pin the parts that need no server and no database: the one-JSON-object
line and its fixed field set (AC3), the span-to-record id bridge (the AC2
mechanism), the resource attributes (AC7), the fail-open exporter wiring (AC8)
and the export-failure redaction (AC9).
"""

from __future__ import annotations

import io
import json
import logging
import re
from typing import Any

import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider

from backend import telemetry
from backend.config import Settings

_ISO_UTC_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_REQUIRED_FIELDS = {
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


def _record(
    message: Any = "hello",
    *,
    name: str = "backend.test",
    level: int = logging.INFO,
    args: tuple[Any, ...] | None = None,
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=None,
    )


def _formatter() -> telemetry.JsonFormatter:
    return telemetry.JsonFormatter(
        service="stockroom",
        service_version="c0ffee",
        environment="test",
    )


def _tracer() -> trace.Tracer:
    return TracerProvider().get_tracer("tests.telemetry")


@pytest.fixture(autouse=True)
def _no_ambient_otlp_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's shell must not decide what these tests configure."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)


# ---------------------------------------------------------------------------
# AC3 — one JSON object per line with the fixed field set
# ---------------------------------------------------------------------------


def test_formatter_emits_one_json_object_with_the_fixed_fields() -> None:
    line = _formatter().format(_record("order accepted"))

    assert "\n" not in line
    payload = json.loads(line)
    assert set(payload) == _REQUIRED_FIELDS
    assert payload["message"] == "order accepted"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "backend.test"
    assert payload["service"] == "stockroom"
    assert payload["service_version"] == "c0ffee"
    assert payload["environment"] == "test"
    assert payload["trace_id"] == ""
    assert payload["span_id"] == ""
    assert _ISO_UTC_MILLIS.match(payload["timestamp"])


def test_formatter_adds_the_request_fields_only_when_present() -> None:
    record = _record("POST /api/orders 201")
    record.method = "POST"
    record.route = "/api/orders"
    record.status_code = 201
    record.duration_ms = 12.5

    payload = json.loads(_formatter().format(record))

    assert payload["method"] == "POST"
    assert payload["route"] == "/api/orders"
    assert payload["status_code"] == 201
    assert payload["duration_ms"] == 12.5
    assert set(payload) == _REQUIRED_FIELDS | {"method", "route", "status_code", "duration_ms"}


def test_formatter_rewrites_a_uvicorn_access_line_without_the_client_address() -> None:
    record = _record(
        '%s - "%s %s HTTP/%s" %d',
        name="uvicorn.access",
        args=("10.1.2.3", "POST", "/api/orders", "1.1", 201),
    )

    line = _formatter().format(record)
    payload = json.loads(line)

    assert "10.1.2.3" not in line
    assert payload["message"] == "POST /api/orders HTTP/1.1 201"
    assert payload["method"] == "POST"
    assert payload["status_code"] == 201


def test_formatter_does_not_break_on_a_surprising_format_string() -> None:
    record = _record("%s and %s", args=("only one",))

    payload = json.loads(_formatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["message"]


# ---------------------------------------------------------------------------
# AC2 — the record's ids come from the active span
# ---------------------------------------------------------------------------


def test_trace_context_filter_puts_the_active_span_ids_on_a_record() -> None:
    record = _record()
    outside = _record()
    filter_ = telemetry.TraceContextFilter()

    assert filter_.filter(outside)
    assert outside.trace_id == ""
    assert outside.span_id == ""

    with _tracer().start_as_current_span("unit") as span:
        context = span.get_span_context()
        expected_trace = format(context.trace_id, "032x")
        expected_span = format(context.span_id, "016x")
        assert filter_.filter(record)
        assert telemetry.current_trace_id() == expected_trace
        assert telemetry.current_span_id() == expected_span

    assert record.trace_id == expected_trace
    assert record.span_id == expected_span


def test_current_trace_id_is_none_outside_a_span_and_the_span_id_inside() -> None:
    # This is the bridge AC2 depends on: remove the span and the request falls
    # back to a minted id, which is the second id the AC forbids.
    assert telemetry.current_trace_id() is None
    assert telemetry.current_span_id() is None

    with _tracer().start_as_current_span("unit") as span:
        context = span.get_span_context()
        assert telemetry.current_trace_id() == format(context.trace_id, "032x")
        assert telemetry.current_span_id() == format(context.span_id, "016x")


# ---------------------------------------------------------------------------
# AC7 — resource attributes
# ---------------------------------------------------------------------------


def test_resource_carries_service_identity_and_the_environment() -> None:
    resource = telemetry.build_resource(
        telemetry.TelemetryConfig(environment="staging", service_version="abc1234")
    )

    assert resource.attributes["service.name"] == "stockroom"
    assert resource.attributes["service.version"] == "abc1234"
    assert resource.attributes["deployment.environment"] == "staging"


def test_changing_the_environment_changes_the_resource() -> None:
    development = telemetry.build_resource(
        telemetry.TelemetryConfig(environment="development", service_version="abc1234")
    )
    production = telemetry.build_resource(
        telemetry.TelemetryConfig(environment="production", service_version="abc1234")
    )

    assert (
        development.attributes["deployment.environment"]
        != production.attributes["deployment.environment"]
    )


def test_commit_sha_is_the_service_version() -> None:
    assert telemetry.resolve_service_version(Settings(commit="c139c5b")) == "c139c5b"
    assert telemetry.resolve_service_version(Settings(commit=" abc1234 ")) == "abc1234"
    assert telemetry.resolve_service_version(Settings(commit="unknown")) == "0.1.0"


def test_an_unknown_commit_falls_back_with_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    telemetry.reset_telemetry()
    stream = io.StringIO()
    with caplog.at_level(logging.WARNING, logger="backend.telemetry"):
        configured = telemetry.configure(Settings(commit="unknown"), log_stream=stream)
    try:
        warnings = [
            record
            for record in caplog.records
            if record.levelno == logging.WARNING and record.name == "backend.telemetry"
        ]
        assert configured.config.service_version == "0.1.0"
        assert len(warnings) == 1

        # The fallback is a JSON line too, not a bare stderr message.
        lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
        assert [line["level"] for line in lines] == ["WARNING"]
        assert lines[0]["service_version"] == "0.1.0"
    finally:
        telemetry.reset_telemetry()
        configured.shutdown()


def test_a_known_commit_logs_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    telemetry.reset_telemetry()
    with caplog.at_level(logging.WARNING, logger="backend.telemetry"):
        configured = telemetry.configure(Settings(commit="c139c5b"), log_stream=io.StringIO())
    try:
        assert configured.config.service_version == "c139c5b"
        assert [record for record in caplog.records if record.name == "backend.telemetry"] == []
    finally:
        telemetry.reset_telemetry()
        configured.shutdown()


# ---------------------------------------------------------------------------
# AC8 / AC9 — export configuration and redaction
# ---------------------------------------------------------------------------


def test_no_endpoint_means_no_exporter() -> None:
    telemetry.reset_telemetry()
    configured = telemetry.configure(Settings(commit="c139c5b", otlp_endpoint=None))
    try:
        assert configured.exporting is False
        assert configured.span_exporter is None
    finally:
        telemetry.reset_telemetry()
        configured.shutdown()


def test_an_endpoint_configures_the_otlp_http_exporter() -> None:
    telemetry.reset_telemetry()
    configured = telemetry.configure(Settings(commit="c139c5b", otlp_endpoint="http://127.0.0.1:1"))
    try:
        assert configured.exporting is True
        assert isinstance(configured.span_exporter, OTLPSpanExporter)
    finally:
        telemetry.reset_telemetry()
        configured.shutdown()


def test_signal_endpoint_appends_the_otlp_path_once() -> None:
    assert (
        telemetry.signal_endpoint("http://collector:4318", "traces")
        == "http://collector:4318/v1/traces"
    )
    assert (
        telemetry.signal_endpoint("http://collector:4318/", "metrics")
        == "http://collector:4318/v1/metrics"
    )
    assert (
        telemetry.signal_endpoint("http://collector:4318/v1/traces", "traces")
        == "http://collector:4318/v1/traces"
    )


def test_otlp_headers_are_parsed_pair_by_pair() -> None:
    token = "Bearer " + "unit-value"

    assert telemetry.parse_otlp_headers(f"authorization={token},x-api-key=unit-key") == {
        "authorization": token,
        "x-api-key": "unit-key",
    }
    assert telemetry.parse_otlp_headers(None) == {}
    assert telemetry.parse_otlp_headers("no-separator") == {}


def test_export_failure_filter_redacts_its_message_and_exception() -> None:
    filter_ = telemetry.ExportFailureFilter(interval_seconds=60.0, clock=lambda: 100.0)
    secret = "Bearer " + "unit-exporter-value"
    record = _record(
        f"Failed to export to http://collector:4318/v1/traces with authorization={secret}",
        level=logging.ERROR,
    )
    record.exc_info = (RuntimeError, RuntimeError(secret), None)
    record.exc_text = f"RuntimeError: {secret}"

    assert filter_.filter(record) is True
    assert "unit-exporter-value" not in record.getMessage()
    assert "collector" not in record.getMessage()
    assert record.exc_info is None
    assert record.exc_text is None


def test_export_failure_filter_logs_at_most_one_line_per_interval() -> None:
    now = [100.0]
    filter_ = telemetry.ExportFailureFilter(interval_seconds=60.0, clock=lambda: now[0])
    first = _record("export failed", level=logging.ERROR)
    second = _record("export failed", level=logging.ERROR)

    assert filter_.filter(first) is True
    assert filter_.filter(second) is False

    now[0] += 61.0
    third = _record("export failed", level=logging.ERROR)
    assert filter_.filter(third) is True


def test_export_failure_filter_leaves_informational_records_alone() -> None:
    filter_ = telemetry.ExportFailureFilter(interval_seconds=60.0, clock=lambda: 100.0)
    record = _record("a normal line")

    assert filter_.filter(record) is True
    assert record.getMessage() == "a normal line"


# ---------------------------------------------------------------------------
# Route templates — no raw path or query string in a metric label
# ---------------------------------------------------------------------------


def _scope(app: FastAPI, path: str, method: str = "GET") -> dict[str, Any]:
    return {
        "type": "http",
        "path": path,
        "root_path": "",
        "method": method,
        "app": app,
    }


def test_route_template_reports_the_template_not_the_raw_path() -> None:
    app = FastAPI()

    @app.post("/api/orders/{id}/cancel")
    def cancel_order(id: str) -> dict[str, str]:  # pragma: no cover - routing only
        return {"id": id}

    assert (
        telemetry.route_template(_scope(app, "/api/orders/0190f2c0-3a55-7a11-8cf1/cancel", "POST"))
        == "/api/orders/{id}/cancel"
    )


def test_route_template_is_a_bounded_placeholder_for_an_unmatched_path() -> None:
    app = FastAPI()

    assert (
        telemetry.route_template(_scope(app, "/api/orders/0190f2c0-3a55-7a11-8cf1"))
        == telemetry.UNMATCHED_ROUTE
    )
    assert telemetry.route_template({"type": "http", "path": "/x", "method": "GET"}) == (
        telemetry.UNMATCHED_ROUTE
    )
