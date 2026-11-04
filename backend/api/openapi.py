"""OpenAPI components shared by the route decorators and the app factory.

FastAPI generates schemas from the Pydantic models in :mod:`backend.api.schemas`,
but three things in the frozen contract have no plain Pydantic spelling:

* the RFC 9457 problem variants are ``allOf`` compositions of ``Problem``;
* responses are referenced as ``#/components/responses/...``;
* path parameters are referenced as ``#/components/parameters/...``.

This module owns those pieces so the routes only name them and
``create_app()`` installs them on the generated document. ``check-contract.mjs``
compares the structural projection of the result with ``openapi.yaml``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from backend.api.schemas import Problem, ProblemError, ValidationProblemError

PROBLEM_MEDIA_TYPE = "application/problem+json"

# Route-level response references. Declaring ``default`` also stops FastAPI from
# adding its own ``422 HTTPValidationError`` to operations the contract leaves
# without one.
VALIDATION_FAILED = {"$ref": "#/components/responses/ValidationFailed"}
NOT_FOUND = {"$ref": "#/components/responses/NotFound"}
INSUFFICIENT_STOCK = {"$ref": "#/components/responses/InsufficientStock"}
INVALID_TRANSITION = {"$ref": "#/components/responses/InvalidTransition"}
ADJUSTMENT_REJECTED = {"$ref": "#/components/responses/AdjustmentRejected"}
SERVICE_UNAVAILABLE = {"$ref": "#/components/responses/ServiceUnavailable"}
UNEXPECTED_ERROR = {"$ref": "#/components/responses/UnexpectedError"}

ORDER_ID_PARAMETERS = [{"$ref": "#/components/parameters/OrderIdPath"}]
SKU_PATH_PARAMETERS = [{"$ref": "#/components/parameters/SkuPath"}]
STATUS_FILTER_PARAMETERS = [
    {
        "name": "status",
        "in": "query",
        "required": False,
        "description": "Return only orders in this state; omit to list every order.",
        "schema": {"$ref": "#/components/schemas/OrderStatus"},
    }
]


def _problem_variant(
    *,
    type_: str,
    status: int,
    description: str,
    errors: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """An ``allOf`` composition the contract uses for a typed problem."""
    extra: dict[str, Any] = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": [type_]},
            "status": {"type": "integer", "enum": [status]},
        },
    }
    if required is not None:
        extra["required"] = required
    if errors is not None:
        extra["properties"]["errors"] = errors
    return {
        "description": description,
        "allOf": [{"$ref": "#/components/schemas/Problem"}, extra],
    }


def _problem_response(schema: dict[str, Any], description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {PROBLEM_MEDIA_TYPE: {"schema": schema}},
    }


def _problem_schema() -> dict[str, Any]:
    """The base problem document, with the contract's ``errors`` item union."""
    schema = Problem.model_json_schema(ref_template="#/components/schemas/{model}")
    schema["properties"]["errors"] = {
        "type": "array",
        "items": {
            "oneOf": [
                {"$ref": "#/components/schemas/ProblemError"},
                {"$ref": "#/components/schemas/ValidationProblemError"},
            ]
        },
    }
    return schema


def _component_schemas() -> dict[str, Any]:
    """Schemas FastAPI cannot derive because no route returns them directly."""
    return {
        "ProblemError": ProblemError.model_json_schema(ref_template="#/components/schemas/{model}"),
        "ValidationProblemError": ValidationProblemError.model_json_schema(
            ref_template="#/components/schemas/{model}"
        ),
        "Problem": _problem_schema(),
        "InsufficientStockProblem": _problem_variant(
            type_="insufficient_stock",
            status=409,
            description="The order was rejected because at least one line is short.",
            required=["errors"],
            errors={
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/components/schemas/ProblemError"},
            },
        ),
        "InvalidTransitionProblem": _problem_variant(
            type_="invalid_transition",
            status=409,
            description="The requested transition is not allowed from the current state.",
        ),
        "WouldBreachReservedProblem": _problem_variant(
            type_="would_breach_reserved",
            status=409,
            description="The adjustment would drive on_hand below reserved.",
        ),
        "NegativeOnHandProblem": _problem_variant(
            type_="negative_on_hand",
            status=409,
            description="The adjustment would make on_hand negative.",
        ),
        "ValidationProblem": _problem_variant(
            type_="validation_error",
            status=422,
            description="The request is malformed or violates an input rule.",
            errors={
                "type": "array",
                "items": {"$ref": "#/components/schemas/ValidationProblemError"},
            },
        ),
        "NotFoundProblem": _problem_variant(
            type_="not_found",
            status=404,
            description="The addressed SKU or order does not exist.",
        ),
        "ServiceUnavailableProblem": _problem_variant(
            type_="service_unavailable",
            status=503,
            description="The database is not reachable.",
        ),
    }


def _component_parameters() -> dict[str, Any]:
    return {
        "SkuPath": {
            "name": "sku",
            "in": "path",
            "required": True,
            "description": "Human-readable unique product code, for example `SKU-1042`.",
            "schema": {"type": "string"},
        },
        "OrderIdPath": {
            "name": "id",
            "in": "path",
            "required": True,
            "description": "Order identifier (UUIDv7).",
            "schema": {"type": "string", "format": "uuid"},
        },
    }


def _component_responses() -> dict[str, Any]:
    return {
        "ValidationFailed": _problem_response(
            {"$ref": "#/components/schemas/ValidationProblem"},
            "The request failed validation; nothing was written.",
        ),
        "NotFound": _problem_response(
            {"$ref": "#/components/schemas/NotFoundProblem"},
            "The addressed SKU or order does not exist.",
        ),
        "InsufficientStock": _problem_response(
            {"$ref": "#/components/schemas/InsufficientStockProblem"},
            "At least one order line cannot be reserved; the whole order is rejected.",
        ),
        "InvalidTransition": _problem_response(
            {"$ref": "#/components/schemas/InvalidTransitionProblem"},
            "The order is not in a state that allows this transition.",
        ),
        "AdjustmentRejected": _problem_response(
            {
                "oneOf": [
                    {"$ref": "#/components/schemas/WouldBreachReservedProblem"},
                    {"$ref": "#/components/schemas/NegativeOnHandProblem"},
                ]
            },
            "The adjustment would corrupt the counters; nothing was written.",
        ),
        "ServiceUnavailable": _problem_response(
            {"$ref": "#/components/schemas/ServiceUnavailableProblem"},
            "The process is serving but the database is unreachable.",
        ),
        "UnexpectedError": _problem_response(
            {"$ref": "#/components/schemas/Problem"},
            "Any other failure, as an RFC 9457 problem document.",
        ),
    }


# FastAPI always describes a path or query parameter inline and appends
# ``openapi_extra`` lists to the generated ones, so the contract's parameter
# components are installed by replacing the operation's list afterwards.
_PARAMETER_OVERRIDES: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("/api/orders", "get"): STATUS_FILTER_PARAMETERS,
    ("/api/orders/{id}", "get"): ORDER_ID_PARAMETERS,
    ("/api/orders/{id}/cancel", "post"): ORDER_ID_PARAMETERS,
    ("/api/orders/{id}/fulfil", "post"): ORDER_ID_PARAMETERS,
    ("/api/stock/{sku}/movements", "get"): SKU_PATH_PARAMETERS,
}


def _install_parameter_overrides(document: dict[str, Any]) -> None:
    paths = document.get("paths", {})
    for (path, method), parameters in _PARAMETER_OVERRIDES.items():
        operation = paths.get(path, {}).get(method)
        if operation is not None:
            operation["parameters"] = parameters


def build_openapi(app: FastAPI):
    """Return an ``openapi`` callable that installs the contract components."""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        document = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = document.setdefault("components", {})
        schemas = components.setdefault("schemas", {})
        for name, schema in _component_schemas().items():
            schemas.setdefault(name, schema)
        components.setdefault("parameters", {}).update(_component_parameters())
        components.setdefault("responses", {}).update(_component_responses())
        _install_parameter_overrides(document)

        app.openapi_schema = document
        return document

    return custom_openapi
