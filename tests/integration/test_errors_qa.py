"""Independent QA coverage for issue #11 — the problem+json error model.

Added by QA in a fresh session from the acceptance criteria in #11 and
``product-spec.md`` §7, not from the implementation's own tests. Nothing here
changes product code.

The 404/409/422/500 assertions run against the real application. A small probe
app built by the same ``create_app`` exercises the framework paths that no
shipping route declares directly (a Pydantic body and an unhandled exception);
it uses the handlers registered for the real application, so reverting the
registration breaks these tests too.

AC map:
- 404/409/422/500 are problem+json with all five fields ....... tests 1-8
- one request-scoped trace id, distinct across requests ....... tests 9-11
- validation errors[] field path/value, no secret echo ........ tests 12-14
- no traceback/SQL/DSN/PII in a 500 or health-probe log ....... tests 15-16
- existing 409 insufficient_stock shape preserved ............. test 17
- validation entry shape matches the contract ................ test 18
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.api.problems import problem
from backend.config import get_settings
from backend.db import seed as seed_module
from backend.main import create_app
from tests.integration.test_seed import _fresh_database, _run_alembic

REPO_ROOT = Path(__file__).resolve().parents[2]

UNREACHABLE_DATABASE_URL = (
    "postgresql+psycopg://qa_user:qa_s3cret@127.0.0.1:1/stockroom?connect_timeout=2"
)

QA_PASSWORD = "hunter2"
QA_TOKEN = "tok_live_qa_must_never_be_echoed"
QA_EMAIL = "qa-person@example.com"
QA_DSN = "postgresql://stockroom:s3cret@db.internal:5432/stockroom"
QA_SQL = "SELECT email, password FROM customers"
QA_EXCEPTION_MESSAGE = f"failed {QA_SQL} against {QA_DSN} for {QA_EMAIL} using {QA_PASSWORD}"
SECRET_MARKERS = (QA_PASSWORD, QA_TOKEN, QA_EMAIL, QA_DSN, QA_SQL)


@pytest.fixture()
def client(database_url: str, monkeypatch: pytest.MonkeyPatch):
    """A TestClient on a fresh, migrated, seeded database (one per test)."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
        monkeypatch.setenv("STOCKROOM_OPERATOR_NAME", "qa-operator")
        get_settings.cache_clear()
        seed_module.seed(engine)
        try:
            with TestClient(create_app()) as test_client:
                yield SimpleNamespace(client=test_client, engine=engine)
        finally:
            get_settings.cache_clear()
            engine.dispose()


class _QALine(BaseModel):
    """A nested body so the field path includes an index (``lines.0.qty``)."""

    sku: str
    qty: int


class _QAOrderPayload(BaseModel):
    """A body no shipping route declares, so FastAPI validates it for us."""

    customer_ref: str = Field(min_length=3, max_length=40)
    lines: list[_QALine]
    password: str = Field(min_length=20)
    api_token: str = Field(pattern=r"^sk_live_[a-z]+$")


@pytest.fixture()
def probe_app() -> FastAPI:
    """The real app plus probe routes for the framework error paths."""
    test_app = create_app()

    @test_app.post("/__qa__/validate")
    def probe_validate(payload: _QAOrderPayload) -> dict[str, str]:
        return {"sku": payload.lines[0].sku}

    @test_app.get("/__qa__/boom")
    def probe_boom() -> None:
        raise RuntimeError(QA_EXCEPTION_MESSAGE)

    @test_app.get("/__qa__/multi")
    def probe_multi(request: Request) -> dict[str, object]:
        """Two problem documents built in one request, plus the state id."""
        first = problem(
            status_code=422,
            type_="validation_error",
            title="Invalid request",
            detail="First error object.",
        )
        second = problem(
            status_code=409,
            type_="invalid_transition",
            title="Invalid transition",
            detail="Second error object.",
        )
        ids = [json.loads(response.body)["trace_id"] for response in (first, second)]
        return {"state": request.state.trace_id, "ids": ids}

    async def capture(request: Request, call_next) -> Response:
        response = await call_next(request)
        test_app.state.last_trace_id = getattr(request.state, "trace_id", None)
        return response

    # Added after create_app's trace middleware, so this is the outer layer and
    # can observe the request-scoped id after the response is produced.
    test_app.add_middleware(BaseHTTPMiddleware, dispatch=capture)
    return test_app


def _contract() -> dict:
    return yaml.safe_load((REPO_ROOT / "openapi.yaml").read_text())


def _required(schema_name: str) -> set[str]:
    return set(_contract()["components"]["schemas"][schema_name]["required"])


def _assert_problem(response, *, status: int, type_: str) -> dict:
    """Assert the five required RFC 9457 fields and a real trace id."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert {"type", "title", "status", "detail", "trace_id"} <= set(body)
    assert body["type"] == type_
    assert isinstance(body["title"], str) and body["title"].strip()
    assert body["status"] == status
    assert isinstance(body["detail"], str) and body["detail"].strip()
    trace_id = body["trace_id"]
    assert isinstance(trace_id, str) and trace_id.strip()
    assert uuid.UUID(hex=trace_id)
    return body


# --- 404 ---------------------------------------------------------------------


def test_unknown_route_is_a_complete_problem(client) -> None:
    body = _assert_problem(client.client.get("/api/no-such-route"), status=404, type_="not_found")
    assert "no-such-route" not in body["detail"]


def test_unknown_resource_ids_are_complete_problems(client) -> None:
    missing_order = str(uuid.uuid4())
    order_body = _assert_problem(
        client.client.get(f"/api/orders/{missing_order}"), status=404, type_="not_found"
    )
    assert missing_order in order_body["detail"]

    movements_body = _assert_problem(
        client.client.get("/api/stock/SKU-DOES-NOT-EXIST/movements"),
        status=404,
        type_="not_found",
    )
    assert "SKU-DOES-NOT-EXIST" in movements_body["detail"]


# --- 409 ---------------------------------------------------------------------


def test_invalid_transition_is_a_complete_problem(client) -> None:
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


def test_adjustment_rejection_is_a_complete_problem(client) -> None:
    # US5-AC3: the other 409 family (stock adjustment) uses the same envelope.
    body = _assert_problem(
        client.client.post(
            "/api/stock/adjust",
            json={"sku": "SKU-1042", "delta": -1_000_000, "note": "QA probe"},
        ),
        status=409,
        type_="negative_on_hand",
    )
    assert "below zero" in body["detail"].lower()


# --- 422 ---------------------------------------------------------------------


def test_malformed_json_is_a_complete_422_not_a_500(client) -> None:
    response = client.client.post(
        "/api/stock/receive",
        content=b'{"sku": "SKU-1042",',
        headers={"content-type": "application/json"},
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    assert "json" in body["detail"].lower()


def test_unknown_sku_names_the_sku_and_is_never_a_500(client) -> None:
    body = _assert_problem(
        client.client.post(
            "/api/orders",
            json={"customer_ref": "CUST-88", "lines": [{"sku": "SKU-NOPE", "qty": 1}]},
        ),
        status=422,
        type_="validation_error",
    )
    assert "SKU-NOPE" in body["detail"]


def test_framework_validation_is_a_complete_problem(probe_app) -> None:
    response = TestClient(probe_app).post(
        "/__qa__/validate",
        json={
            "customer_ref": "CUST-88",
            "lines": [{"sku": "SKU-1042", "qty": "many"}],
            "password": QA_TOKEN,  # long enough
            "api_token": "sk_live_ok",
        },
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    assert body["errors"]


# --- 500 ---------------------------------------------------------------------


def test_forced_500_is_a_complete_problem(probe_app) -> None:
    body = _assert_problem(
        TestClient(probe_app).get("/__qa__/boom"), status=500, type_="unexpected"
    )
    assert body["detail"] == "An unexpected error occurred."
    assert "errors" not in body


# --- Trace id scope ----------------------------------------------------------


def test_one_request_has_one_trace_id_for_every_error_object(probe_app) -> None:
    response = TestClient(probe_app).get("/__qa__/multi")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"]
    assert body["state"] == body["ids"][0] == body["ids"][1]
    assert uuid.UUID(hex=body["state"])


def test_forced_500_trace_id_is_the_request_state_id(probe_app) -> None:
    body = _assert_problem(
        TestClient(probe_app).get("/__qa__/boom"), status=500, type_="unexpected"
    )
    assert body["trace_id"] == probe_app.state.last_trace_id


def test_different_requests_get_different_trace_ids(client) -> None:
    first = _assert_problem(client.client.get("/api/does-not-exist"), status=404, type_="not_found")
    second = _assert_problem(client.client.get("/api/also-missing"), status=404, type_="not_found")
    assert first["trace_id"] != second["trace_id"]


# --- Validation entries ------------------------------------------------------


def test_validation_entries_carry_the_field_path_and_offending_value(probe_app) -> None:
    response = TestClient(probe_app).post(
        "/__qa__/validate",
        json={
            "customer_ref": "CUST-88",
            "lines": [{"sku": "SKU-1042", "qty": "many"}],
            "password": "sk_live_password_that_is_long_enough",
            "api_token": "sk_live_ok",
        },
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    by_field = {entry["field"]: entry for entry in body["errors"]}
    assert by_field["lines.0.qty"]["value"] == "many"
    assert by_field["lines.0.qty"]["message"]


def test_validation_entries_never_echo_a_password_or_token(probe_app) -> None:
    response = TestClient(probe_app).post(
        "/__qa__/validate",
        json={
            "customer_ref": "CUST-88",
            "lines": [{"sku": "SKU-1042", "qty": 1}],
            "password": QA_PASSWORD,  # too short
            "api_token": QA_TOKEN,  # does not match the pattern
        },
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    by_field = {entry["field"]: entry for entry in body["errors"]}

    # The fields are named, but their values are never echoed.
    assert by_field["password"]["field"] == "password"
    assert "value" not in by_field["password"]
    assert by_field["api_token"]["field"] == "api_token"
    assert "value" not in by_field["api_token"]
    assert QA_PASSWORD not in response.text
    assert QA_TOKEN not in response.text


def test_validation_entries_omit_structured_and_null_input(probe_app) -> None:
    response = TestClient(probe_app).post(
        "/__qa__/validate",
        json={
            "customer_ref": None,
            "lines": {"sku": "SKU-1042", "qty": 1},
            "password": "sk_live_password_that_is_long_enough",
            "api_token": "sk_live_ok",
        },
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    by_field = {entry["field"]: entry for entry in body["errors"]}
    assert by_field["customer_ref"]["field"] == "customer_ref"
    assert "value" not in by_field["customer_ref"]
    assert by_field["lines"]["field"] == "lines"
    assert "value" not in by_field["lines"]


# --- Logs --------------------------------------------------------------------


def test_500_log_has_no_traceback_sql_dsn_or_pii(
    probe_app, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="backend.api.errors"):
        body = _assert_problem(
            TestClient(probe_app).get("/__qa__/boom"), status=500, type_="unexpected"
        )

    assert body["trace_id"] in caplog.text
    assert "RuntimeError" in caplog.text
    assert "Traceback" not in caplog.text
    assert 'File "' not in caplog.text
    for marker in SECRET_MARKERS:
        assert marker not in caplog.text
        assert marker not in json.dumps(body)


def test_health_probe_failure_log_has_no_traceback_sql_dsn_or_pii(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
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
    assert "Traceback" not in logged
    assert 'File "' not in logged
    for marker in ("qa_user", "qa_s3cret", "postgresql", "SELECT"):
        assert marker not in logged


# --- Contract shapes ---------------------------------------------------------


def test_insufficient_stock_entries_match_the_contract_problem_error(client) -> None:
    response = client.client.post(
        "/api/orders",
        json={
            "customer_ref": "CUST-88",
            "lines": [{"sku": "SKU-1042", "qty": 2}, {"sku": "SKU-5127", "qty": 7}],
        },
    )

    body = _assert_problem(response, status=409, type_="insufficient_stock")
    entry = body["errors"][0]
    assert entry == {"sku": "SKU-5127", "requested": 7, "available": 6, "short_by": 1}
    assert set(entry) == _required("ProblemError")
    assert entry["short_by"] == entry["requested"] - entry["available"]


def test_validation_entries_match_the_contract_validation_problem_error(probe_app) -> None:
    response = TestClient(probe_app).post(
        "/__qa__/validate",
        json={
            "customer_ref": "CUST-88",
            "lines": [{"sku": "SKU-1042", "qty": "many"}],
            "password": QA_PASSWORD,
            "api_token": QA_TOKEN,
        },
    )

    body = _assert_problem(response, status=422, type_="validation_error")
    schema = _contract()["components"]["schemas"]["ValidationProblemError"]
    required = set(schema["required"])
    allowed = set(schema["properties"])

    assert body["errors"]
    for entry in body["errors"]:
        assert required <= set(entry)
        assert set(entry) <= allowed
        if "value" in entry:
            assert isinstance(entry["value"], (str, int, float, bool))
