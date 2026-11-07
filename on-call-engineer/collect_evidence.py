"""Read-only, allowlisted evidence collection (T7.1, issue #61).

The query set is a constant keyed by alert name. No query text is ever taken
from the alert payload, so a label cannot inject PromQL. Every outbound request
is a GET; the collector imports no database driver and writes nothing under
``/api``.

Observation failures (Loki down, app down, a query returning non-200) are
recorded as ``unavailable`` and never abort the packet: an incident is exactly
when those services are unhealthy.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Any

import httpx
from packet import utc_timestamp

# The three diagnostic expressions from `observability/alerts.yaml`, with the
# rule's comparison removed so the packet carries the observed value rather
# than the boolean. The runbooks' "first three checks" read the same values.
ORDER_ERROR_RATIO_QUERY = """(
  sum by (service_name, service_version, deployment_environment) (
    rate(stockroom_http_request_duration_seconds_count{http_route=~\"/api/orders(/.*)?\",
      http_response_status_code=~\"5..\"}[5m])
  )
  /
  sum by (service_name, service_version, deployment_environment) (
    rate(stockroom_http_request_duration_seconds_count{http_route=~"/api/orders(/.*)?"}[5m])
  )
)"""

ORDER_P95_LATENCY_QUERY = """histogram_quantile(
  0.95,
  sum by (le, service_name, service_version, deployment_environment) (
    rate(stockroom_http_request_duration_seconds_bucket{http_route=~"/api/orders(/.*)?"}[5m])
  )
)"""

INVARIANT_DRIFT_QUERY = """label_replace(
  stockroom_stock_invariant_drift_ratio,
  "__name__", "stockroom_stock_invariant_drift",
  "__name__", ".*"
)"""

ORDERS_PLACED_RATE_QUERY = "sum(rate(stockroom_orders_placed_total[5m]))"
ORDERS_FAILED_RATE_QUERY = "sum by (reason) (rate(stockroom_orders_failed_total[5m]))"

# Keyed by alert name. An unknown alert name records the alert and runs no
# Prometheus query.
PROMETHEUS_QUERIES: dict[str, tuple[tuple[str, str], ...]] = {
    "StockroomOrderErrorRateHigh": (
        ("order_error_ratio", ORDER_ERROR_RATIO_QUERY),
        ("orders_placed_rate", ORDERS_PLACED_RATE_QUERY),
        ("orders_failed_rate", ORDERS_FAILED_RATE_QUERY),
    ),
    "StockroomOrderLatencyP95High": (
        ("order_p95_latency", ORDER_P95_LATENCY_QUERY),
        ("orders_placed_rate", ORDERS_PLACED_RATE_QUERY),
        ("orders_failed_rate", ORDERS_FAILED_RATE_QUERY),
    ),
    "InventoryInvariantViolation": (
        ("invariant_drift", INVARIANT_DRIFT_QUERY),
        ("orders_placed_rate", ORDERS_PLACED_RATE_QUERY),
        ("orders_failed_rate", ORDERS_FAILED_RATE_QUERY),
    ),
}

# One fixed selector. It never comes from the alert payload.
LOKI_SELECTOR = '{container=~"stockroom-app.*"} | json | status_code >= 500'

# The log fields the packet may copy. Everything else in the JSON line is
# dropped, including any customer reference or credential a future line adds.
LOG_FIELDS = (
    "timestamp",
    "level",
    "message",
    "method",
    "route",
    "status_code",
    "duration_ms",
    "trace_id",
    "order_id",
    "sku",
)

TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

# Only these three read endpoints, only GET.
APP_PATHS: tuple[tuple[str, str], ...] = (
    ("healthz", "/healthz"),
    ("version", "/api/version"),
    ("invariants", "/api/invariants"),
)

APP_RESULT_FIELDS: dict[str, tuple[str, ...]] = {
    "healthz": ("status", "db"),
    "version": ("version", "commit", "build_time", "environment"),
    "invariants": ("ok", "violations"),
}

INVARIANT_VIOLATION_FIELDS = ("rule", "sku", "expected", "actual", "order_id")
PROBLEM_FIELDS = ("type", "title", "status", "detail", "trace_id")

LOGGER = logging.getLogger("stockroom.oncall.evidence")


class PrometheusUnavailable(RuntimeError):
    """``/api/v1/alerts`` or ``/api/v1/rules`` could not be read."""


class Collector:
    """The read-only HTTP client behind one evidence packet."""

    def __init__(
        self,
        config: Any,
        *,
        clock: Any = time.time,
        client: httpx.Client | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._logger = logger or LOGGER
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=config.http_timeout_seconds, follow_redirects=False
        )

    def close(self) -> None:
        """Close the client only when this collector created it."""
        if self._owns_client:
            self._client.close()

    # -- alert source ------------------------------------------------------

    def fetch_alerts(self) -> list[dict[str, Any]]:
        """The active alerts; a transport or HTTP failure is fatal for the poll."""
        try:
            response = self._get(f"{self._config.prometheus_url}/api/v1/alerts")
        except httpx.HTTPError as exc:
            raise PrometheusUnavailable(type(exc).__name__) from None
        body = self._success_body(response)
        alerts = (body.get("data") or {}).get("alerts")
        if not isinstance(alerts, list):
            raise PrometheusUnavailable("unexpected response")
        return [alert for alert in alerts if isinstance(alert, dict)]

    def fetch_rules(self) -> dict[str, dict[str, Any]]:
        """Alerting rules keyed by name, for the ``expr`` and ``for`` fields."""
        try:
            response = self._get(f"{self._config.prometheus_url}/api/v1/rules")
        except httpx.HTTPError as exc:
            raise PrometheusUnavailable(type(exc).__name__) from None
        body = self._success_body(response)
        rules: dict[str, dict[str, Any]] = {}
        for group in (body.get("data") or {}).get("groups") or []:
            if not isinstance(group, dict):
                continue
            for rule in group.get("rules") or []:
                if (
                    isinstance(rule, dict)
                    and rule.get("type") == "alerting"
                    and isinstance(rule.get("name"), str)
                ):
                    rules.setdefault(rule["name"], rule)
        return rules

    def _success_body(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code != 200:
            raise PrometheusUnavailable(f"HTTP {response.status_code}")
        body = self._json(response)
        if not isinstance(body, dict) or body.get("status") != "success":
            raise PrometheusUnavailable("unexpected response")
        return body

    # -- observations ------------------------------------------------------

    def collect(self, alert: Mapping[str, Any], now: int) -> dict[str, Any]:
        """Every allowlisted observation for one alert; failures are recorded."""
        labels = alert.get("labels") if isinstance(alert.get("labels"), Mapping) else {}
        name = str(labels.get("alertname") or "")
        return {
            "prometheus": self._prometheus(name, now),
            "logs": self._logs(now),
            "app": self._app(),
        }

    def _prometheus(self, alert_name: str, now: int) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for name, query in PROMETHEUS_QUERIES.get(alert_name, ()):
            observations.append(self._query(name, query, now))
        return observations

    def _query(self, name: str, query: str, now: int) -> dict[str, Any]:
        observation: dict[str, Any] = {
            "name": name,
            "query": query,
            "status": "unavailable",
            "http_status": None,
            "error": None,
            "result": None,
        }
        try:
            response = self._get(
                f"{self._config.prometheus_url}/api/v1/query",
                params={"query": query, "time": str(now)},
            )
        except httpx.HTTPError as exc:
            observation["error"] = type(exc).__name__
            return observation

        observation["http_status"] = response.status_code
        if response.status_code != 200:
            observation["error"] = f"HTTP {response.status_code}"
            return observation
        body = self._json(response)
        if not isinstance(body, dict) or body.get("status") != "success":
            observation["error"] = "unexpected response"
            return observation

        observation["status"] = "ok"
        observation["result"] = (body.get("data") or {}).get("result") or []
        return observation

    def _logs(self, now: int) -> dict[str, Any]:
        start = now - self._config.lookback_minutes * 60
        observation: dict[str, Any] = {
            "selector": LOKI_SELECTOR,
            "status": "unavailable",
            "error": None,
            "http_status": None,
            "window": {"start": utc_timestamp(start), "end": utc_timestamp(now)},
            "samples": [],
            "trace_ids": [],
        }
        try:
            response = self._get(
                f"{self._config.loki_url}/loki/api/v1/query_range",
                params={
                    "query": LOKI_SELECTOR,
                    "limit": str(self._config.log_samples),
                    "start": str(start * 10**9),
                    "end": str(now * 10**9),
                    "direction": "backward",
                },
            )
        except httpx.HTTPError as exc:
            observation["error"] = type(exc).__name__
            return observation

        observation["http_status"] = response.status_code
        if response.status_code != 200:
            observation["error"] = f"HTTP {response.status_code}"
            return observation
        body = self._json(response)
        if not isinstance(body, dict) or body.get("status") != "success":
            observation["error"] = "unexpected response"
            return observation

        samples = self._samples(body)
        trace_ids = self._trace_ids(samples)
        observation["samples"] = samples
        observation["trace_ids"] = trace_ids
        observation["status"] = "ok"
        return observation

    def _samples(self, body: Mapping[str, Any]) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        limit = self._config.log_samples
        for stream in (body.get("data") or {}).get("result") or []:
            if not isinstance(stream, Mapping):
                continue
            for value in stream.get("values") or []:
                if len(samples) >= limit:
                    return samples
                sample = self._sample(value)
                if sample is not None:
                    samples.append(sample)
        return samples

    def _sample(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return None
        nanoseconds, line = value[0], value[1]
        try:
            parsed = json.loads(line) if isinstance(line, str) else {}
        except ValueError:
            return None
        if not isinstance(parsed, dict):
            return None
        sample = {key: parsed[key] for key in LOG_FIELDS if key in parsed}
        if "timestamp" not in sample:
            try:
                sample["timestamp"] = utc_timestamp(int(nanoseconds) // 10**9)
            except (TypeError, ValueError):
                return None
        return {
            key: item
            for key, item in sample.items()
            if item is None or isinstance(item, (str, int, float, bool))
        }

    def _trace_ids(self, samples: list[dict[str, Any]]) -> list[str]:
        """Trace ids, preferring the order journey over other 5xx requests.

        The Loki selector is fixed and also matches health-check failures; the
        three ids a responder gets should point at the journey the alert is
        about when the window contains one. Ties keep the response order.
        """
        ordered = sorted(
            samples,
            key=lambda sample: 0 if str(sample.get("route") or "").startswith("/api/orders") else 1,
        )
        trace_ids: list[str] = []
        for sample in ordered:
            trace_id = sample.get("trace_id")
            if (
                isinstance(trace_id, str)
                and TRACE_ID_PATTERN.fullmatch(trace_id)
                and trace_id not in trace_ids
            ):
                trace_ids.append(trace_id)
        return trace_ids[: self._config.trace_samples]

    def _app(self) -> dict[str, Any]:
        observations: dict[str, Any] = {}
        for name, path in APP_PATHS:
            observations[name] = self._app_call(name, path)
        return observations

    def _app_call(self, name: str, path: str) -> dict[str, Any]:
        observation: dict[str, Any] = {
            "method": "GET",
            "path": path,
            "status": "unavailable",
            "http_status": None,
            "error": None,
            "result": None,
        }
        try:
            response = self._get(f"{self._config.app_url}{path}")
        except httpx.HTTPError as exc:
            observation["error"] = type(exc).__name__
            return observation

        observation["http_status"] = response.status_code
        body = self._json(response)
        if 200 <= response.status_code < 300:
            observation["status"] = "ok"
            observation["result"] = self._filter_result(name, body)
            return observation

        # A problem+json body is useful evidence, but only its fixed fields.
        observation["error"] = f"HTTP {response.status_code}"
        if isinstance(body, dict) and body.get("type"):
            observation["result"] = {key: body[key] for key in PROBLEM_FIELDS if key in body}
        return observation

    def _filter_result(self, name: str, body: Any) -> dict[str, Any] | None:
        if not isinstance(body, dict):
            return None
        fields = APP_RESULT_FIELDS[name]
        result = {key: body[key] for key in fields if key in body}
        if name == "invariants" and isinstance(result.get("violations"), list):
            result["violations"] = [
                {key: item[key] for key in INVARIANT_VIOLATION_FIELDS if key in item}
                for item in result["violations"]
                if isinstance(item, dict)
            ]
        return result

    # -- transport ---------------------------------------------------------

    def _get(self, url: str, params: Mapping[str, str] | None = None) -> httpx.Response:
        return self._client.get(url, params=dict(params) if params else None)

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None
