"""The problem+json error model and its request-scoped ``trace_id`` (issue #11).

Covers ``product-spec.md`` §7 and AGENTS.md rule 4: every error response — including
an unknown route, a wrong method, framework validation, a missing order and an
unhandled failure — is ``application/problem+json`` with ``type``, ``title``,
``status``, ``detail`` and a non-empty ``trace_id``. Validation failures carry the
field path and the offending value in ``errors[]`` without echoing secrets, and no
response body or error log leaks a stack trace, SQL, a connection string or PII.

A small probe app built by ``create_app`` exercises the framework paths (a Pydantic
body and an exception) that no production route declares directly; the handlers
under test are the ones registered for the real application.
"""

from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy import create_engine

from backend.api.problems import problem
from backend.config import get_settings
from backend.db import seed as seed_module
from backend.main import create_app
from tests.integration.test_seed import _fresh_database, _run_alembic

UNREACHABLE_DATABASE_URL = (
    "postgresql+psycopg://nobody:nobody@127.0.0.1:1/stockroom?connect_timeout=2"
)

SECRET_PASSWORD = "hunter2-super-secret"
SECRET_EMAIL = "ada@example.com"
SECRET_DSN = "postgresql://stockroom:s3cret@db.internal:5432/stockroom"
SECRET_SQL = "SELECT email, password FROM customers"
SECRET_MESSAGE = (
    f"failed to run {SECRET_SQL} against {SECRET_DSN} for {SECRET_EMAIL} using {SECRET_PASSWORD}"
)


@pytest.fixture()
def client(database_url: str, monkeypatch: pytest.MonkeyPatch):
    """A TestClient on a fresh, migrated, seeded database (one per test)."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
        monkeypatch.setenv("STOCKROOM_OPERATOR_NAME", "demo-operator")
        get_settings.cache_clear()
        seed_module.seed(engine)
        from backend.main import app

        with TestClient(app) as test_client:
            yield SimpleNamespace(client=test_client, engine=engine)
        get_settings.cache_clear()
        engine.dispose()


class _ProbePayload(BaseModel):
    """A body no production route declares, so FastAPI validates it for us."""

    sku: str
    qty: int
    password: str = Field(min_length=20)


@pytest.fixture()
def probe_app() -> FastAPI:
    """A fresh real app plus probe routes for the framework error paths."""
    app = create_app()

    @app.post("/__probe__/validate")
    def probe_validate(payload: _ProbePayload) -> dict[str, str]:
        return {"sku": payload.sku}

    @app.get("/__probe__/boom")
    def probe_boom() -> None:
        raise RuntimeError(SECRET_MESSAGE)

    @app.get("/__probe__/trace")
    def probe_trace(request: Request) -> dict[str, str]:
        from backend.api.problems import current_trace_id

        first = current_trace_id()
        response = problem(
            status_code=422,
            type_="validation_error",
            title="Invalid request",
            detail="Probe.",
        )
        return {
            "state": request.state.trace_id,
            "first": first,
            "second": current_trace_id(),
            "problem": json.loads(response.body)["trace_id"],
        }

    return app


def _assert_problem(response, *, status: int, type_: str) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == type_
    assert body["title"]
    assert body["status"] == status
    assert body["detail"]
    trace_id = body["trace_id"]
    assert isinstance(trace_id, str) and trace_id.strip()
    # A UUIDv4 hex id is 32 lowercase hex characters.
    assert uuid.UUID(hex=trace_id)
    return body


# --- Routing and method errors ------------------------------------------------


def test_unknown_route_is_a_404_problem(client) -> None:
    body = _assert_problem(client.client.get("/api/does-not-exist"), status=404, type_="not_found")
    assert "does-not-exist" not in body["detail"]


def test_wrong_method_is_a_405_problem(client) -> None:
    response = client.client.delete("/api/orders")

    _assert_problem(response, status=405, type_="method_not_allowed")
    assert response.headers["allow"]


# --- Validation errors --------------------------------------------------------


def test_unknown_sku_on_order_creation_is_a_422_naming_the_sku(client) -> None:
    # US1-AC5: the route/validation logic belongs to #8; #11 proves the envelope.
    response = client.client.post(
        "/api/orders",
        json={"customer_ref": "CUST-88", "lines": [{"sku": "SKU-NOPE", "qty": 1}]},
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    assert "SKU-NOPE" in body["detail"]


def test_malformed_json_is_a_422_not_a_500(client) -> None:
    response = client.client.post(
        "/api/stock/receive",
        content=b'{"sku": "SKU-1042",',
        headers={"content-type": "application/json"},
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    assert "json" in body["detail"].lower()


def test_framework_validation_errors_report_field_path_and_value(probe_app) -> None:
    secret = "hunter2"
    response = TestClient(probe_app).post(
        "/__probe__/validate",
        json={"sku": "SKU-1042", "qty": "many", "password": secret},
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    by_field = {entry["field"]: entry for entry in body["errors"]}

    assert by_field["qty"]["value"] == "many"
    assert by_field["qty"]["message"]

    # The secret field is named, but its value is never echoed.
    assert by_field["password"]["field"] == "password"
    assert "value" not in by_field["password"]
    assert secret not in response.text
    assert SECRET_PASSWORD not in response.text


def test_framework_validation_of_a_missing_field_omits_the_whole_body(probe_app) -> None:
    response = TestClient(probe_app).post(
        "/__probe__/validate",
        json={"sku": "SKU-1042", "password": SECRET_PASSWORD},
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    by_field = {entry["field"]: entry for entry in body["errors"]}

    assert by_field["qty"]["field"] == "qty"
    assert "value" not in by_field["qty"]
    assert SECRET_PASSWORD not in response.text


# --- Domain errors keep their shape ------------------------------------------


def test_insufficient_stock_errors_keep_the_short_line_shape(client) -> None:
    response = client.client.post(
        "/api/orders",
        json={
            "customer_ref": "CUST-88",
            "lines": [{"sku": "SKU-1042", "qty": 2}, {"sku": "SKU-5127", "qty": 7}],
        },
    )

    body = _assert_problem(response, status=409, type_="insufficient_stock")
    assert body["errors"] == [{"sku": "SKU-5127", "requested": 7, "available": 6, "short_by": 1}]


def test_unknown_order_id_is_a_404_problem(client) -> None:
    missing = str(uuid.uuid4())

    body = _assert_problem(
        client.client.get(f"/api/orders/{missing}"), status=404, type_="not_found"
    )
    assert missing in body["detail"]


def test_invalid_transition_is_a_409_problem(client) -> None:
    created = client.client.post(
        "/api/orders",
        json={"customer_ref": "CUST-88", "lines": [{"sku": "SKU-1042", "qty": 1}]},
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    assert client.client.post(f"/api/orders/{order_id}/cancel").status_code == 200

    body = _assert_problem(
        client.client.post(f"/api/orders/{order_id}/cancel"),
        status=409,
        type_="invalid_transition",
    )
    assert "cancelled" in body["detail"].lower()


# --- The unhandled path -------------------------------------------------------


def test_unhandled_exception_is_a_generic_500_without_leaks(
    probe_app, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="backend.api.errors"):
        # Default TestClient behaviour re-raises any exception that escapes the
        # ASGI app, so this also proves the middleware contains the failure.
        response = TestClient(probe_app).get("/__probe__/boom")

    body = _assert_problem(response, status=500, type_="unexpected")
    assert body["detail"] == "An unexpected error occurred."
    assert "errors" not in body

    # The response body leaks neither the exception message nor a stack trace.
    for secret in (SECRET_PASSWORD, SECRET_EMAIL, SECRET_DSN, SECRET_SQL):
        assert secret not in response.text
    assert "traceback" not in response.text.lower()
    assert "RuntimeError" not in response.text

    # The log names only the exception class and the request's trace id.
    messages = [
        record.getMessage() for record in caplog.records if record.name == "backend.api.errors"
    ]
    assert messages
    logged = "\n".join(messages)
    assert "RuntimeError" in logged
    assert body["trace_id"] in logged
    for secret in (SECRET_PASSWORD, SECRET_EMAIL, SECRET_DSN, SECRET_SQL):
        assert secret not in logged
    assert "traceback" not in logged.lower()


def test_health_probe_failure_log_has_no_stack_trace_or_connection_details(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # AC5 applies to every error log, not only the catch-all handler. The health
    # probe used to log with exc_info=True, which prints the driver traceback.
    monkeypatch.setenv("STOCKROOM_DATABASE_URL", UNREACHABLE_DATABASE_URL)
    get_settings.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="backend.db.session"):
            response = TestClient(create_app()).get("/healthz")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["trace_id"]

    logged = caplog.text
    assert "health probe failed" in logged.lower()
    assert "traceback" not in logged.lower()
    assert "nobody:nobody" not in logged
    assert "postgresql" not in logged.lower()


# --- Trace id scope -----------------------------------------------------------


def test_trace_id_is_stable_within_one_request(probe_app) -> None:
    response = TestClient(probe_app).get("/__probe__/trace")

    assert response.status_code == 200
    body = response.json()
    assert body["state"]
    assert body["state"] == body["first"] == body["second"] == body["problem"]


def test_trace_ids_are_unique_per_request(client) -> None:
    trace_ids = {
        _assert_problem(client.client.get("/api/does-not-exist"), status=404, type_="not_found")[
            "trace_id"
        ],
        _assert_problem(
            client.client.post(
                "/api/stock/adjust",
                json={"sku": "SKU-1042", "delta": 0, "note": "noop"},
            ),
            status=422,
            type_="validation_error",
        )["trace_id"],
        _assert_problem(
            client.client.post(
                "/api/orders",
                json={"customer_ref": "CUST-88", "lines": [{"sku": "SKU-NOPE", "qty": 1}]},
            ),
            status=422,
            type_="validation_error",
        )["trace_id"],
    }

    assert len(trace_ids) == 3
