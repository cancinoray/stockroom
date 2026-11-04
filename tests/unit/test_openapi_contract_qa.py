"""QA check for #32: the generated document carries every contract component detail.

``test_openapi_contract.py`` on the issue branch pins the route-level drift
classes. This file closes the remaining gaps the external ``check:contract``
script covers: the required fields of ``Product``, ``Movement`` and
``InvariantReport``, the request-model constraints for receive/adjust, and that
every declared 4xx/5xx response on every operation is an
``application/problem+json`` problem response.
"""

from __future__ import annotations

import pytest

from backend.main import create_app

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


@pytest.fixture(scope="module")
def document() -> dict:
    return create_app().openapi()


def test_every_error_status_declares_a_problem_response(document: dict) -> None:
    responses = document["components"]["responses"]

    for path, item in document["paths"].items():
        for method in METHODS:
            operation = item.get(method)
            if operation is None:
                continue
            for status, response in operation["responses"].items():
                if status == "default" or status[0] not in "45":
                    continue
                where = f"{method.upper()} {path} {status}"
                assert response["$ref"].startswith("#/components/responses/"), where

                name = response["$ref"].rsplit("/", 1)[-1]
                content = responses[name]["content"]
                assert "application/problem+json" in content, where


def test_response_component_required_fields_match_the_contract(document: dict) -> None:
    schemas = document["components"]["schemas"]
    expected = {
        "Order": {"id", "customer_ref", "status", "created_at", "lines", "movements"},
        "OrderLine": {"sku", "name", "qty", "unit_price_cents"},
        "StockRow": {
            "sku",
            "name",
            "on_hand",
            "reserved",
            "available",
            "reorder_point",
            "unit_price_cents",
            "low",
        },
        "Product": {"sku", "name", "unit_price_cents", "reorder_point", "available", "low"},
        "Movement": {
            "id",
            "sku",
            "reason",
            "delta_on_hand",
            "delta_reserved",
            "actor",
            "note",
            "order_id",
            "created_at",
            "on_hand_after",
        },
        "InvariantReport": {"ok", "violations"},
        "InvariantViolation": {"rule", "sku", "expected", "actual"},
        "Health": {"status", "db"},
        "Version": {"version", "commit", "build_time", "environment"},
        "Problem": {"type", "title", "status", "detail", "trace_id"},
        "ProblemError": {"sku", "requested", "available", "short_by"},
        "ValidationProblemError": {"field"},
    }
    for name, required in expected.items():
        assert set(schemas[name]["required"]) == required, name


def test_request_models_declare_the_contract_required_fields(document: dict) -> None:
    schemas = document["components"]["schemas"]

    receive = schemas["ReceiveRequest"]
    assert set(receive["required"]) == {"sku", "qty"}
    assert receive["properties"]["qty"]["minimum"] == 1

    adjust = schemas["AdjustRequest"]
    assert set(adjust["required"]) == {"sku", "delta", "note"}
    assert adjust["properties"]["delta"]["not"] == {"enum": [0]}
    assert adjust["properties"]["note"]["minLength"] == 1

    order = schemas["CreateOrderRequest"]
    assert set(order["required"]) == {"customer_ref", "lines"}
    assert order["properties"]["lines"]["minItems"] == 1
    assert order["properties"]["customer_ref"]["minLength"] == 3
    assert order["properties"]["customer_ref"]["maxLength"] == 40


def test_problem_variants_keep_the_contract_detail(document: dict) -> None:
    schemas = document["components"]["schemas"]

    insufficient = schemas["InsufficientStockProblem"]["allOf"][1]
    assert insufficient["required"] == ["errors"]
    assert insufficient["properties"]["errors"]["minItems"] == 1
    assert insufficient["properties"]["errors"]["items"]["$ref"].endswith("/ProblemError")

    validation = schemas["ValidationProblem"]["allOf"][1]
    assert validation["properties"]["status"]["enum"] == [422]
    assert validation["properties"]["errors"]["items"]["$ref"].endswith("/ValidationProblemError")
    assert schemas["Problem"]["properties"]["errors"]["items"]["oneOf"] == [
        {"$ref": "#/components/schemas/ProblemError"},
        {"$ref": "#/components/schemas/ValidationProblemError"},
    ]
    assert schemas["ValidationProblemError"]["properties"]["value"]["oneOf"] == [
        {"type": "string"},
        {"type": "integer"},
        {"type": "number"},
        {"type": "boolean"},
    ]
