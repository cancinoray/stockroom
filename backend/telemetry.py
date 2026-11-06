"""The single owner of Stockroom's traces, metrics and JSON logs (T6.1, #55).

Everything observability-related that runs inside the app is configured here:

* **traces** — one ``TracerProvider``. The FastAPI instrumentation creates the
  request's server span; database child spans come from SQLAlchemy engine
  events registered here, so the reservation transaction is visible without a
  second instrumentation library and without editing an endpoint.
* **metrics** — one ``MeterProvider`` with exactly the five journey instruments
  (``stockroom_*``), recorded by :class:`RequestTelemetryMiddleware`. The
  instrumentation's own HTTP metrics are switched off so the metric set stays
  the five names the dashboard and the alert rules build on.
* **logs** — one JSON formatter on the stdlib logging tree, including the
  uvicorn loggers, so every line is one JSON object carrying the same trace and
  span ids as the trace.
* **the drift gauge** — the stock invariant check runs in the background on its
  own autocommit connection, never inside a request's transaction.

The rules the tests pin down:

* fail-open: an unset OTLP endpoint means "no exporter", never a failure, and
  an export failure is rate-limited and redacted rather than fatal;
* one trace id: the active span's 32-hex id is *the* request id and
  ``problem+json`` reuses it;
* allowlist only: request-derived span attributes are limited to the route
  template, the method, the status, the problem type and a parsed ``order_id``.
  URLs that could carry a query string, user agents and peer addresses are
  redacted before the span is exported.

Providers are never installed process-globally: they are handed to the FastAPI
instrumentation explicitly, which is what lets a test configure in-memory
exporters without touching network state.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.metrics import NoOpMeterProvider, Observation
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanProcessor,
)
from opentelemetry.trace import SpanKind, Status, StatusCode
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.config import Settings, get_settings
from backend.db.session import engine_for
from backend.domain.invariants import (
    ORDER_RESERVATION_QUERY,
    STOCK_LEDGER_QUERY,
    InvariantReport,
    check_invariants,
)

logger = logging.getLogger(__name__)

SERVICE_NAME = "stockroom"
DEFAULT_SERVICE_VERSION = "0.1.0"
UNKNOWN_COMMIT = "unknown"
INSTRUMENTATION_NAME = "stockroom.telemetry"

# ``product-spec.md`` §7: the order routes whose journey these metrics describe.
PLACE_ORDER_ROUTE = "/api/orders"
ORDER_ROUTES = frozenset(
    {
        PLACE_ORDER_ROUTE,
        "/api/orders/{id}/cancel",
        "/api/orders/{id}/fulfil",
    }
)
UNMATCHED_ROUTE = "<unmatched>"
REDACTED = "redacted"

ORDERS_PLACED_METRIC = "stockroom_orders_placed_total"
ORDERS_FAILED_METRIC = "stockroom_orders_failed_total"
REQUEST_DURATION_METRIC = "stockroom_http_request_duration_seconds"
RESERVATION_CONFLICTS_METRIC = "stockroom_reservation_conflicts_total"
STOCK_DRIFT_METRIC = "stockroom_stock_invariant_drift"

# Fixed, documented bucket set: one histogram, stable across deployments so a
# dashboard does not have to guess the boundaries.
REQUEST_DURATION_BUCKETS_SECONDS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

PROBLEM_TYPE_ATTRIBUTE = "error.type"

# The problem types that make an order journey fail loudly in the trace. A 4xx
# is not an error span by itself; these two are the journey's rejections.
ERROR_PROBLEM_TYPES = frozenset({"insufficient_stock", "invalid_transition"})

_REQUEST_LOG_FIELDS = ("method", "route", "status_code", "duration_ms")
_LOG_LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
_QUIET_LOGGERS = {
    "sqlalchemy.engine": logging.WARNING,
    "urllib3": logging.WARNING,
    "urllib3.connectionpool": logging.WARNING,
    "httpx": logging.WARNING,
}
_EXPORT_LOGGERS = (
    "opentelemetry.sdk.trace.export",
    "opentelemetry.sdk.metrics._internal.export",
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "opentelemetry.exporter.otlp.proto.http.metric_exporter",
)

# Attributes the HTTP instrumentation derives from the raw request. The URL can
# carry a query string, the user agent and peer address identify a caller —
# none of that is on the rule 4 allowlist, so they are overwritten before export.
_REDACTED_URL_ATTRIBUTES = ("http.target", "http.url", "url.full", "url.query")
_REDACTED_CALLER_ATTRIBUTES = (
    "http.user_agent",
    "user_agent.original",
    "net.peer.ip",
    "http.client_ip",
    "client.address",
    "net.sock.peer.addr",
)

_MAX_CAPTURED_BODY = 64 * 1024
_DRIFT_FAILURE_WARNING_INTERVAL_SECONDS = 60.0
_EXPORT_FAILURE_WARNING_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class TelemetryConfig:
    """The resolved telemetry settings for one process."""

    environment: str = "development"
    service_version: str = DEFAULT_SERVICE_VERSION
    otlp_endpoint: str | None = None
    otlp_headers: str | None = None
    export_interval_millis: int = 5000
    drift_interval_seconds: float = 30.0
    export_timeout_seconds: float = 3.0
    commit_was_unknown: bool = False


def resolve_service_version(settings: Settings) -> str:
    """The commit SHA from ``/api/version``, or ``0.1.0``.

    Pure on purpose: the fallback warning is emitted by :class:`Telemetry`
    after the JSON handler is installed, so it is a JSON line like every other.
    """
    commit = (settings.commit or "").strip()
    if not commit or commit == UNKNOWN_COMMIT:
        return DEFAULT_SERVICE_VERSION
    return commit


def config_from_settings(settings: Settings) -> TelemetryConfig:
    """Snap a :class:`Settings` instance into an immutable telemetry config."""
    return TelemetryConfig(
        environment=settings.environment,
        service_version=resolve_service_version(settings),
        otlp_endpoint=(settings.otlp_endpoint or "").strip() or None,
        otlp_headers=(settings.otlp_headers or "").strip() or None,
        export_interval_millis=max(int(settings.telemetry_export_interval_millis), 100),
        drift_interval_seconds=max(float(settings.telemetry_drift_interval_seconds), 0.05),
        export_timeout_seconds=max(float(settings.telemetry_export_timeout_seconds), 0.1),
        commit_was_unknown=(settings.commit or "").strip() in {"", UNKNOWN_COMMIT},
    )


def build_resource(config: TelemetryConfig) -> Resource:
    """The resource every span, log record and metric carries (AC7)."""
    return Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": config.service_version,
            "deployment.environment": config.environment,
        }
    )


def signal_endpoint(base: str, signal: str) -> str:
    """The OTLP/HTTP URL for ``signal`` from a base ``OTEL_EXPORTER_OTLP_ENDPOINT``."""
    endpoint = base.rstrip("/")
    suffix = f"/v1/{signal}"
    if endpoint.endswith(suffix):
        return endpoint
    return f"{endpoint}{suffix}"


def parse_otlp_headers(raw: str | None) -> dict[str, str]:
    """Parse ``OTEL_EXPORTER_OTLP_HEADERS`` (``key=value,key2=value2``)."""
    if not raw:
        return {}
    headers: dict[str, str] = {}
    for item in raw.split(","):
        key, separator, value = item.partition("=")
        key = key.strip()
        if separator and key:
            headers[key] = value.strip()
    return headers


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------


def _utc_timestamp(created: float) -> str:
    """ISO-8601 UTC, millisecond precision, ``Z`` suffix."""
    stamp = datetime.fromtimestamp(created, UTC)
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _message_and_access_fields(record: logging.LogRecord) -> tuple[str, dict[str, Any]]:
    """The message, plus the fields a uvicorn access line can be rebuilt from.

    uvicorn logs access lines as ``'%s - "%s %s HTTP/%s" %d'`` with the client
    address first. Interpolating that would put the caller's address in the log,
    so the line is rebuilt without it.

    The third argument is ``scope["path"] + "?" + query_string``. A query can
    carry a credential, an API key or customer data (AC4), so only the path
    survives; the app's own request record already logs the matched route
    template.
    """
    if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
        _client, method, path, version, status_code = record.args
        fields: dict[str, Any] = {"method": str(method)}
        with contextlib.suppress(TypeError, ValueError):
            fields["status_code"] = int(status_code)
        target = str(path).split("?", 1)[0]
        return f"{method} {target} HTTP/{version} {status_code}", fields
    try:
        return record.getMessage(), {}
    except Exception:  # noqa: BLE001 - a bad format string must not lose the line
        return str(record.msg), {}


def _record_id(record: logging.LogRecord, name: str, fallback: Any) -> str:
    value = getattr(record, name, None)
    if isinstance(value, str):
        return value
    return fallback() or ""


class JsonFormatter(logging.Formatter):
    """One JSON object per line with the fixed field set of AC3."""

    def __init__(self, *, service: str, service_version: str, environment: str) -> None:
        super().__init__()
        self._service = service
        self._service_version = service_version
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        message, access_fields = _message_and_access_fields(record)
        payload: dict[str, Any] = {
            "timestamp": _utc_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "service": self._service,
            "service_version": self._service_version,
            "environment": self._environment,
            "trace_id": _record_id(record, "trace_id", current_trace_id),
            "span_id": _record_id(record, "span_id", current_span_id),
        }
        for name in _REQUEST_LOG_FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        for name, value in access_fields.items():
            payload.setdefault(name, value)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TraceContextFilter(logging.Filter):
    """Put the active span's trace and span ids on every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id() or ""
        record.span_id = current_span_id() or ""
        return True


class ExportFailureFilter(logging.Filter):
    """Rate-limit export failures and keep the endpoint and headers out (AC8/AC9).

    The SDK logs an export failure with its exception text, which can name the
    endpoint. Only a fixed line survives, at most once per interval.
    """

    def __init__(
        self,
        *,
        interval_seconds: float = _EXPORT_FAILURE_WARNING_INTERVAL_SECONDS,
        clock: Any = time.monotonic,
    ) -> None:
        super().__init__()
        self._interval = interval_seconds
        self._clock = clock
        self._last = float("-inf")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            return True
        now = self._clock()
        if now - self._last < self._interval:
            return False
        self._last = now
        record.msg = "Telemetry export failed; samples were dropped."
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


# --------------------------------------------------------------------------
# Database child spans (AC1)
# --------------------------------------------------------------------------

_DB_EVENTS_INSTALLED = False


def install_db_span_events() -> None:
    """Record one child span per SQL statement, under the active request span.

    The statements run in a worker thread (``asyncio.to_thread``) and still see
    the request span, because the context is copied into the thread. Nothing
    outside a recording span — the drift check, a script — gets a span.
    """
    global _DB_EVENTS_INSTALLED
    if _DB_EVENTS_INSTALLED:
        return
    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(Engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(Engine, "handle_error", _handle_db_error)
    _DB_EVENTS_INSTALLED = True


def _operation(statement: str) -> str:
    parts = statement.lstrip().split(None, 1)
    return parts[0].upper() if parts else "SQL"


def _before_cursor_execute(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    telemetry = _state
    if telemetry is None or not telemetry.exporting:
        return
    parent = trace.get_current_span()
    if not parent.is_recording():
        return
    operation = _operation(statement)
    span = telemetry.tracer.start_span(
        f"db.query {operation}",
        context=trace.set_span_in_context(parent),
        kind=SpanKind.CLIENT,
        attributes={"db.system": "postgresql", "db.operation": operation},
    )
    context._stockroom_db_span = span


def _after_cursor_execute(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    span = getattr(context, "_stockroom_db_span", None)
    if span is None:
        return
    context._stockroom_db_span = None
    try:
        rowcount = getattr(cursor, "rowcount", None)
        if isinstance(rowcount, int) and rowcount >= 0:
            span.set_attribute("db.rows_affected", rowcount)
    finally:
        span.end()


def _handle_db_error(exception_context: Any) -> None:
    execution_context = getattr(exception_context, "execution_context", None)
    span = getattr(execution_context, "_stockroom_db_span", None)
    if span is None:
        return
    execution_context._stockroom_db_span = None
    original = getattr(exception_context, "original_exception", None)
    span.set_attribute("db.error.type", type(original).__name__)
    span.set_status(Status(StatusCode.ERROR, "database error"))
    span.end()


# --------------------------------------------------------------------------
# Telemetry instance
# --------------------------------------------------------------------------


class Telemetry:
    """Providers, instruments and the drift monitor for one process."""

    def __init__(
        self,
        config: TelemetryConfig,
        *,
        span_exporter: SpanExporter | None = None,
        metric_reader: MetricReader | None = None,
        log_stream: Any | None = None,
    ) -> None:
        self.config = config
        self.resource = build_resource(config)
        self._log_stream = log_stream
        self._handler: logging.Handler | None = None
        self._drift_task: asyncio.Task[None] | None = None
        self._drift_violations = 0
        self._drift_reported: set[tuple[str, str]] = set()
        self._drift_warning_at = float("-inf")

        otlp_spans = _otlp_span_exporter(config) if span_exporter is None else None
        self.span_exporter: SpanExporter | None = span_exporter or otlp_spans
        otlp_metrics = _otlp_metric_exporter(config) if metric_reader is None else None

        self.exporting = self.span_exporter is not None or metric_reader is not None
        self.tracer_provider = TracerProvider(resource=self.resource)
        if self.span_exporter is not None:
            # An injected exporter is a test collector: export synchronously so
            # an assertion right after the request sees the span. The OTLP
            # exporter batches, so request latency never waits on the network.
            processor: SpanProcessor = (
                SimpleSpanProcessor(self.span_exporter)
                if span_exporter is not None
                else BatchSpanProcessor(self.span_exporter)
            )
            self.tracer_provider.add_span_processor(processor)
            self.exporting = True
        self.tracer = self.tracer_provider.get_tracer(INSTRUMENTATION_NAME)

        readers: list[MetricReader] = []
        if metric_reader is not None:
            readers.append(metric_reader)
        if otlp_metrics is not None:
            readers.append(
                PeriodicExportingMetricReader(
                    otlp_metrics,
                    export_interval_millis=config.export_interval_millis,
                )
            )
            self.exporting = True
        self.meter_provider = MeterProvider(resource=self.resource, metric_readers=readers)
        self.meter = self.meter_provider.get_meter(INSTRUMENTATION_NAME)
        self._create_instruments()

        if self.exporting:
            _install_export_redaction()

        self.configure_logging()
        if config.commit_was_unknown:
            # One warning per configuration, now that the line is JSON (AC7).
            logger.warning(
                "Build metadata reports an unknown commit; exporting service.version=%s",
                DEFAULT_SERVICE_VERSION,
            )

    # -- metrics ---------------------------------------------------------

    def _create_instruments(self) -> None:
        self.request_duration = self.meter.create_histogram(
            REQUEST_DURATION_METRIC,
            unit="s",
            description="Wall-clock duration of one HTTP request.",
            explicit_bucket_boundaries_advisory=list(REQUEST_DURATION_BUCKETS_SECONDS),
        )
        self.orders_placed = self.meter.create_counter(
            ORDERS_PLACED_METRIC,
            unit="1",
            description="Orders accepted, one per successful POST /api/orders.",
        )
        self.orders_failed = self.meter.create_counter(
            ORDERS_FAILED_METRIC,
            unit="1",
            description="Order requests rejected, labelled by problem type.",
        )
        self.reservation_conflicts = self.meter.create_counter(
            RESERVATION_CONFLICTS_METRIC,
            unit="1",
            description="Orders rejected because stock was insufficient.",
        )
        self.stock_drift_gauge = self.meter.create_observable_gauge(
            STOCK_DRIFT_METRIC,
            callbacks=[self._observe_stock_drift],
            unit="1",
            description="Stock cache/ledger disagreements found by the last check.",
        )

    def _observe_stock_drift(self, options: Any) -> list[Observation]:
        return [Observation(self._drift_violations)]

    def record_request(
        self,
        *,
        span: trace.Span,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
        order_id: str | None,
    ) -> None:
        """Record one request: span attributes, one latency sample, counters, one log."""
        safe_route = route or UNMATCHED_ROUTE
        problem_type = _problem_type_on(span)
        reason = problem_type or ("unexpected" if status_code >= 500 else "http_error")

        # Recorded inside the server span's context, so the sample carries the
        # request's trace id as its exemplar (AC2).
        self.request_duration.record(
            duration_seconds,
            {
                "http.request.method": method,
                "http.route": safe_route,
                "http.response.status_code": status_code,
            },
        )

        if method == "POST" and safe_route in ORDER_ROUTES:
            if 200 <= status_code < 300:
                if safe_route == PLACE_ORDER_ROUTE:
                    self.orders_placed.add(1)
            else:
                self.orders_failed.add(1, {"reason": reason})
                if reason == "insufficient_stock":
                    self.reservation_conflicts.add(1, {"reason": reason})

        self._annotate_span(
            span,
            method=method,
            route=safe_route,
            status_code=status_code,
            order_id=order_id,
            problem_type=problem_type,
        )

        logger.info(
            "%s %s %s",
            method,
            safe_route,
            status_code,
            extra={
                "method": method,
                "route": safe_route,
                "status_code": status_code,
                "duration_ms": round(duration_seconds * 1000.0, 3),
            },
        )

    def _annotate_span(
        self,
        span: trace.Span | None,
        *,
        method: str,
        route: str,
        status_code: int,
        order_id: str | None,
        problem_type: str | None,
    ) -> None:
        if span is None or not span.is_recording():
            return
        attributes = getattr(span, "attributes", None) or {}
        for key in _REDACTED_URL_ATTRIBUTES:
            if key in attributes:
                span.set_attribute(key, REDACTED)
        for key in _REDACTED_CALLER_ATTRIBUTES:
            if key in attributes:
                span.set_attribute(key, REDACTED)
        span.set_attribute("http.request.method", method)
        span.set_attribute("http.route", route)
        span.set_attribute("http.response.status_code", status_code)
        if order_id:
            span.set_attribute("order.id", order_id)
        if problem_type:
            span.set_attribute(PROBLEM_TYPE_ATTRIBUTE, problem_type)

    # -- invariants / drift gauge (AC6) ----------------------------------

    async def check_invariants_once(self) -> int:
        """Run one check off the event loop and update the gauge."""
        report = await asyncio.to_thread(read_invariant_report)
        self._apply_invariant_report(report)
        return self._drift_violations

    def _apply_invariant_report(self, report: InvariantReport) -> None:
        self._drift_violations = len(report.violations)
        found = {(str(violation.rule), violation.sku) for violation in report.violations}
        for rule, sku in sorted(found - self._drift_reported):
            logger.warning("Stock invariant drift detected (rule=%s, sku=%s)", rule, sku)
        self._drift_reported = found

    async def _monitor_drift(self) -> None:
        while True:
            try:
                await self.check_invariants_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a failed check must not stop the loop
                self._warn_drift_failure(type(exc).__name__)
            await asyncio.sleep(self.config.drift_interval_seconds)

    def _warn_drift_failure(self, error_name: str) -> None:
        now = time.monotonic()
        if now - self._drift_warning_at < _DRIFT_FAILURE_WARNING_INTERVAL_SECONDS:
            return
        self._drift_warning_at = now
        logger.warning("Stock invariant drift check failed (%s)", error_name)

    def force_flush(self, timeout_millis: int = 1000) -> None:
        """Flush buffered spans and metrics; used by tests and shutdown paths."""
        self.tracer_provider.force_flush(timeout_millis)
        self.meter_provider.force_flush(timeout_millis)

    @property
    def drift_violations(self) -> int:
        """The value the gauge currently reports."""
        return self._drift_violations

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Re-assert the JSON logging and start the drift monitor.

        One monitor per process, not one per server: a second app in the same
        process (an integration test's client, say) reuses the running task
        rather than starting a second check loop.
        """
        self.configure_logging()
        task = self._drift_task
        if task is not None and not task.done() and not task.get_loop().is_closed():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._drift_task = loop.create_task(self._monitor_drift(), name="stockroom-drift-monitor")

    def shutdown(self) -> None:
        """Stop the providers and detach logging.

        Only for an instance a caller owns (a test). The app-level instance is
        left running for the process's lifetime: shutting it down would silently
        drop the spans of any app that still holds it.
        """
        self.detach_logging()
        self.meter_provider.shutdown()
        self.tracer_provider.shutdown()

    async def stop(self) -> None:
        task = self._drift_task
        if task is None or task.done():
            self._drift_task = None
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if task.get_loop() is not loop:
            # Another live event loop owns the monitor (a second TestClient in
            # the same process). Leave it to its owner's stop(); awaiting a
            # future attached to this loop would raise.
            return
        self._drift_task = None
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def configure_logging(self) -> None:
        """Install the JSON handler on the app and uvicorn loggers (idempotent).

        Applied at app construction and again on startup: uvicorn installs its
        own logging config before importing the app in some launch paths, so
        the startup call is what makes its access and error lines JSON.
        """
        stream = self._log_stream if self._log_stream is not None else sys.stderr
        handler = self._handler
        if handler is None or getattr(handler, "stream", None) is not stream:
            handler = logging.StreamHandler(stream)
            handler.setFormatter(
                JsonFormatter(
                    service=SERVICE_NAME,
                    service_version=self.config.service_version,
                    environment=self.config.environment,
                )
            )
            handler.addFilter(TraceContextFilter())
            handler._stockroom_json = True  # type: ignore[attr-defined]
            self._handler = handler

        for name in _LOG_LOGGERS:
            target = logging.getLogger(name) if name else logging.getLogger()
            for existing in list(target.handlers):
                if existing is handler:
                    continue
                # uvicorn installs its own handlers before importing the app, so
                # its loggers are taken over completely. Root keeps foreign
                # handlers (pytest's capture) and only loses ours.
                if name or getattr(existing, "_stockroom_json", False):
                    target.removeHandler(existing)
            if handler not in target.handlers:
                target.addHandler(handler)
            target.setLevel(logging.INFO)
            if name:
                target.propagate = False

        for name, level in _QUIET_LOGGERS.items():
            logging.getLogger(name).setLevel(level)

    def detach_logging(self) -> None:
        """Remove this instance's handler (the test seam for ``reset_telemetry``)."""
        handler = self._handler
        if handler is None:
            return
        for name in _LOG_LOGGERS:
            target = logging.getLogger(name) if name else logging.getLogger()
            if handler in target.handlers:
                target.removeHandler(handler)


def _problem_type_on(span: trace.Span | None) -> str | None:
    if span is None or not span.is_recording():
        return None
    attributes = getattr(span, "attributes", None) or {}
    value = attributes.get(PROBLEM_TYPE_ATTRIBUTE)
    return value if isinstance(value, str) else None


def _otlp_span_exporter(config: TelemetryConfig) -> SpanExporter | None:
    if not config.otlp_endpoint:
        return None
    return OTLPSpanExporter(
        endpoint=signal_endpoint(config.otlp_endpoint, "traces"),
        headers=parse_otlp_headers(config.otlp_headers),
        timeout=config.export_timeout_seconds,
    )


def _otlp_metric_exporter(config: TelemetryConfig) -> OTLPMetricExporter | None:
    if not config.otlp_endpoint:
        return None
    return OTLPMetricExporter(
        endpoint=signal_endpoint(config.otlp_endpoint, "metrics"),
        headers=parse_otlp_headers(config.otlp_headers),
        timeout=config.export_timeout_seconds,
    )


def _install_export_redaction() -> None:
    """One shared filter for every exporter logger.

    Shared on purpose: a single export attempt can fail on the trace exporter
    and on the metric exporter in the same interval, and the contract is *one*
    rate-limited line, not one per signal.
    """
    filter_ = ExportFailureFilter()
    for name in _EXPORT_LOGGERS:
        target = logging.getLogger(name)
        for existing in list(target.filters):
            if isinstance(existing, ExportFailureFilter):
                target.removeFilter(existing)
        target.addFilter(filter_)


# --------------------------------------------------------------------------
# Request middleware
# --------------------------------------------------------------------------


def route_template(scope: Mapping[str, Any]) -> str:
    """The matched route template, or a bounded placeholder.

    Metrics and span attributes must never carry a raw path or a query string,
    so ``/api/orders/<id>/cancel`` is reported as ``/api/orders/{id}/cancel``
    and an unmatched request as ``<unmatched>``.
    """
    app = scope.get("app")
    routes = getattr(app, "routes", ()) if app is not None else ()
    for route in _flatten_routes(routes):
        matches = getattr(route, "matches", None)
        if matches is None:
            continue
        try:
            match, _ = matches(scope)
        except Exception:  # noqa: BLE001 - an odd route must not break telemetry
            continue
        if match == Match.FULL:
            return str(getattr(route, "path", UNMATCHED_ROUTE))
    return UNMATCHED_ROUTE


def _flatten_routes(routes: Sequence[Any]) -> Iterator[Any]:
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _flatten_routes(nested.routes)
        else:
            yield route


def _as_order_id(value: object) -> str | None:
    """A canonical order id, or ``None``.

    Only a parseable UUID reaches the span: a path segment or a body value that
    is not an order id is not an identifier this service emits.
    """
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _order_id_for(scope: Mapping[str, Any], route: str, body: bytes) -> str | None:
    if route not in ORDER_ROUTES:
        return None
    if route == PLACE_ORDER_ROUTE:
        if not body:
            return None
        try:
            document = json.loads(bytes(body))
        except (ValueError, UnicodeDecodeError):
            return None
        return _as_order_id(document.get("id")) if isinstance(document, Mapping) else None
    params = scope.get("path_params") or {}
    return _as_order_id(params.get("id") if isinstance(params, Mapping) else None)


class RequestTelemetryMiddleware:
    """One span-aware pass over every HTTP request.

    A pure ASGI middleware (not ``BaseHTTPMiddleware``) so it shares the task
    and context of the route: the problem type recorded by
    :func:`note_problem` and the span attributes are visible here.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        telemetry = get_telemetry()
        method = str(scope.get("method", ""))
        route = route_template(scope)
        capture_body = method == "POST" and route == PLACE_ORDER_ROUTE
        started = time.perf_counter()
        status_code = 500
        body = bytearray()
        recorded = False

        def record() -> None:
            # The ASGI instrumentation ends the server span when the last
            # response body message is forwarded, so everything this middleware
            # contributes has to happen before that `send`.
            nonlocal recorded
            if recorded:
                return
            recorded = True
            telemetry.record_request(
                span=trace.get_current_span(),
                method=method,
                route=route,
                status_code=status_code,
                duration_seconds=time.perf_counter() - started,
                order_id=_order_id_for(scope, route, bytes(body)),
            )

        async def send_with_capture(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                if capture_body:
                    chunk = message.get("body") or b""
                    if len(body) < _MAX_CAPTURED_BODY:
                        body.extend(chunk[: _MAX_CAPTURED_BODY - len(body)])
                if not message.get("more_body", False):
                    record()
            await send(message)

        try:
            await self.app(scope, receive, send_with_capture)
        finally:
            # A disconnect before the final body message still gets a sample.
            record()


# --------------------------------------------------------------------------
# Invariant check
# --------------------------------------------------------------------------


def read_invariant_report() -> InvariantReport:
    """Run both invariant queries on their own autocommit connection.

    Autocommit means no transaction is held open between the two statements:
    the check cannot sit on a lock a stock write is waiting for.
    """
    database_url = get_settings().database_url
    if not database_url:
        return InvariantReport()
    engine = engine_for(database_url)
    with engine.connect() as connection:
        connection = connection.execution_options(isolation_level="AUTOCOMMIT")
        stock_rows = connection.execute(text(STOCK_LEDGER_QUERY)).mappings().all()
        order_rows = connection.execute(text(ORDER_RESERVATION_QUERY)).mappings().all()
    return check_invariants(stock_rows, order_rows)


# --------------------------------------------------------------------------
# Module API used by the app, the error handlers and the tests
# --------------------------------------------------------------------------

_state: Telemetry | None = None


def current_trace_id() -> str | None:
    """The active span's 32-hex trace id, or ``None`` outside a span."""
    span_context = trace.get_current_span().get_span_context()
    return format(span_context.trace_id, "032x") if span_context.is_valid else None


def current_span_id() -> str | None:
    """The active span's 16-hex span id, or ``None`` outside a span."""
    span_context = trace.get_current_span().get_span_context()
    return format(span_context.span_id, "016x") if span_context.is_valid else None


def note_problem(status_code: int, problem_type: str) -> None:
    """Put the problem type on the active span — never a stack trace (AC1)."""
    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.set_attribute(PROBLEM_TYPE_ATTRIBUTE, problem_type)
    if status_code >= 500 or problem_type in ERROR_PROBLEM_TYPES:
        span.set_status(Status(StatusCode.ERROR, problem_type))


def configure(
    settings: Settings | None = None,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
    log_stream: Any | None = None,
) -> Telemetry:
    """Build the process telemetry from ``settings`` and install it.

    Injecting ``span_exporter``/``metric_reader`` replaces the OTLP exporters,
    which is how the suites run offline with in-memory collectors.
    """
    global _state
    config = config_from_settings(settings or get_settings())
    telemetry = Telemetry(
        config,
        span_exporter=span_exporter,
        metric_reader=metric_reader,
        log_stream=log_stream,
    )
    _state = telemetry
    install_db_span_events()
    telemetry.configure_logging()
    return telemetry


def get_telemetry() -> Telemetry:
    """The current instance, configured from settings on first use."""
    if _state is None:
        return configure()
    return _state


def reset_telemetry() -> None:
    """Test seam: forget the current instance and remove its log handler.

    Providers are deliberately *not* shut down here: an app created earlier
    still holds them, and a shut-down provider would silently drop the spans of
    every later test that reuses that app. The batch threads are daemons.
    """
    global _state
    telemetry = _state
    _state = None
    if telemetry is not None:
        telemetry.detach_logging()


def start() -> None:
    """Start logging and the drift monitor (called from the app's lifespan)."""
    get_telemetry().start()


async def stop() -> None:
    """Stop the drift monitor (called from the app's lifespan)."""
    telemetry = _state
    if telemetry is not None:
        await telemetry.stop()


def instrument_app(app: FastAPI) -> None:
    """Add the metrics middleware and the server-span instrumentation."""
    telemetry = get_telemetry()
    app.add_middleware(RequestTelemetryMiddleware)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.tracer_provider,
        # The five ``stockroom_*`` metrics are the contract; the
        # instrumentation's own HTTP metrics would add names nobody asked for.
        meter_provider=NoOpMeterProvider(),
        exclude_spans=["receive", "send"],
        # Headers are never captured: an Authorization or API-key header must
        # not reach a span (AC4).
        http_capture_headers_server_request=[],
        http_capture_headers_server_response=[],
    )
