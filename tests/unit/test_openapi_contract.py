"""The generated OpenAPI document matches the frozen contract's structure (#32).

The full structural diff is the T3.1 check script on PR #31. This test pins the
drift classes that script found so a regression fails `make test` as well:
order path parameters, the declared 201s, the request/response component names
and the problem-response declarations.
"""

from __future__ import annotations

import pytest

from backend.main import create_app


@pytest.fixture(scope="module")
def document() -> dict:
    return create_app().openapi()


def _operation(document: dict, path: str, method: str) -> dict:
    return document["paths"][path][method]


def test_order_paths_use_the_contract_id_parameter(document: dict) -> None:
    # AC: detail, cancel and fulfil use {id}, while the URLs stay the same.
    assert "/api/orders/{order_id}" not in document["paths"]
    assert "/api/orders/{order_id}/cancel" not in document["paths"]
    assert "/api/orders/{order_id}/fulfil" not in document["paths"]

    for path, method in (
        ("/api/orders/{id}", "get"),
        ("/api/orders/{id}/cancel", "post"),
        ("/api/orders/{id}/fulfil", "post"),
    ):
        assert _operation(document, path, method)["parameters"] == [
            {"$ref": "#/components/parameters/OrderIdPath"}
        ]


def test_create_receive_and_adjust_declare_201(document: dict) -> None:
    for path in ("/api/orders", "/api/stock/receive", "/api/stock/adjust"):
        responses = _operation(document, path, "post")["responses"]
        assert "201" in responses, path
        assert "200" not in responses, path


def test_request_bodies_reference_the_contract_models(document: dict) -> None:
    expected = {
        "/api/orders": "CreateOrderRequest",
        "/api/stock/receive": "ReceiveRequest",
        "/api/stock/adjust": "AdjustRequest",
    }
    for path, model in expected.items():
        request_body = _operation(document, path, "post")["requestBody"]
        assert request_body["required"] is True
        assert request_body["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{model}"
        }

    order_line = document["components"]["schemas"]["CreateOrderLine"]
    assert set(order_line["required"]) == {"sku", "qty"}
    assert order_line["properties"]["qty"]["minimum"] == 1


def test_response_schemas_use_the_contract_component_names(document: dict) -> None:
    schemas = document["components"]["schemas"]

    for name in (
        "Order",
        "OrderLine",
        "OrderStatus",
        "StockRow",
        "Product",
        "Movement",
        "MovementReason",
        "InvariantReport",
        "InvariantViolation",
        "Problem",
        "ProblemError",
        "ValidationProblemError",
        "Health",
        "Version",
    ):
        assert name in schemas, name

    assert "HealthResponse" not in schemas
    assert "VersionResponse" not in schemas
    assert set(schemas["Order"]["required"]) == {
        "id",
        "customer_ref",
        "status",
        "created_at",
        "lines",
        "movements",
    }
    assert set(schemas["StockRow"]["required"]) == {
        "sku",
        "name",
        "on_hand",
        "reserved",
        "available",
        "reorder_point",
        "unit_price_cents",
        "low",
    }


def test_problem_responses_are_declared_on_every_error_status(document: dict) -> None:
    expected = {
        ("/api/orders", "post"): {"201", "409", "422"},
        ("/api/stock/receive", "post"): {"201", "404", "422"},
        ("/api/stock/adjust", "post"): {"201", "404", "409", "422"},
        ("/api/orders/{id}", "get"): {"200", "404"},
        ("/api/orders/{id}/cancel", "post"): {"200", "404", "409"},
        ("/api/orders/{id}/fulfil", "post"): {"200", "404", "409"},
        ("/api/stock/{sku}/movements", "get"): {"200", "404"},
        ("/healthz", "get"): {"200", "503"},
    }
    for (path, method), statuses in expected.items():
        declared = set(_operation(document, path, method)["responses"]) - {"default"}
        assert declared == statuses, f"{path} {method}"

    insufficient = _operation(document, "/api/orders", "post")["responses"]["409"]
    assert insufficient["$ref"] == "#/components/responses/InsufficientStock"
    rejected = _operation(document, "/api/stock/adjust", "post")["responses"]["409"]
    assert rejected["$ref"] == "#/components/responses/AdjustmentRejected"


def test_health_and_version_match_the_contract(document: dict) -> None:
    health = document["components"]["schemas"]["Health"]
    assert health["properties"]["status"]["enum"] == ["ok"]
    assert sorted(health["properties"]["db"]["enum"]) == ["not_configured", "ok"]

    version = document["components"]["schemas"]["Version"]
    assert set(version["required"]) == {"version", "commit", "build_time", "environment"}
