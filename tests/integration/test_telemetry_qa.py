"""Independent QA coverage for T6.1 / #55 (AC2).

AC2 is absolute ("a request must never carry two ids"). The issue tests cover
the successful order and the two 409 journey rejections; this file covers the
remaining failing routes, where a framework error handler could mint its own
id: unknown route, unknown order id, request validation, malformed JSON and a
wrong method.

The QA probes for the healthz 503 and the live query-string leak are not
repeated here: the engineer's committed regressions
``test_healthz_503_problem_trace_id_is_the_request_span_trace_id`` and the live
uvicorn query sentinel in ``test_a_live_uvicorn_writes_one_json_object_per_line``
own those clauses (testing-guidelines §4: do not duplicate).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend import telemetry
from tests.integration.test_telemetry import (
    _HEX_TRACE_ID,
    _log_records,
    _running_stack,
    _seeded_database,
    _trace_id,
)


def test_every_failing_request_problem_id_is_its_span_trace_id(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (
        _seeded_database(database_url, monkeypatch) as engine,
        _running_stack(engine, monkeypatch) as stack,
    ):
        _assert_failing_requests_carry_one_id(stack)


def _assert_failing_requests_carry_one_id(stack: Any) -> None:
    cases = [
        # (method, path, kwargs, expected status, expected route template)
        ("GET", "/api/does-not-exist", {}, 404, telemetry.UNMATCHED_ROUTE),
        ("POST", "/api/orders/not-a-uuid/cancel", {}, 404, "/api/orders/{id}/cancel"),
        (
            "POST",
            "/api/orders",
            {"json": {"customer_ref": "CUST-88", "lines": [{"sku": "SKU-1042", "qty": 0}]}},
            422,
            "/api/orders",
        ),
        (
            "POST",
            "/api/orders",
            {"content": b"{", "headers": {"content-type": "application/json"}},
            422,
            "/api/orders",
        ),
        ("DELETE", "/api/orders", {}, 405, telemetry.UNMATCHED_ROUTE),
    ]

    for method, path, kwargs, expected_status, route in cases:
        response = stack.client.request(method, path, **kwargs)
        label = f"{method} {path} -> {response.status_code}"
        assert response.status_code == expected_status, f"{label}: {response.text}"

        body = response.json()
        assert _HEX_TRACE_ID.match(body["trace_id"]), f"{label}: not 32 hex"
        trace_id = body["trace_id"]

        # The span recorded for this request must have the same trace id.
        matching_spans = [
            span for span in stack.spans.get_finished_spans() if _trace_id(span) == trace_id
        ]
        assert matching_spans, f"{label}: no span carries {trace_id}"

        # Every log line for the request carries that one id, never a minted one.
        records = [record for record in _log_records(stack.logs) if record["trace_id"] == trace_id]
        assert records, f"{label}: no log record carries {trace_id}"
        request_records = [
            record
            for record in records
            if record.get("route") == route and record.get("status_code") == expected_status
        ]
        assert request_records, f"{label}: no request-scoped log record for {route}"
