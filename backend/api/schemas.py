"""Pydantic models mirroring the frozen ``openapi.yaml`` contract.

These describe the wire shapes so FastAPI's generated document names and
structures every component the way the contract does. The endpoints build
their response documents from database rows and return ``JSONResponse``
objects, so adding a ``response_model`` changes the documentation and never
the runtime body or status code.

Two shapes cannot be expressed with plain Pydantic annotations: the contract's
``oneOf`` unions and ``nullable`` fields (OpenAPI 3.0 spelling). ``WithJsonSchema``
and ``json_schema_extra`` pin those without changing the Python type.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema

from backend.domain import MovementReason, OrderStatus


class _StrictModel(BaseModel):
    """Request models reject coercion, matching the hand-written validators.

    ``qty: "3"`` and ``qty: 1.5`` were already 422s; strict mode keeps that
    true now that FastAPI validates the body before the handler runs.
    """

    model_config = ConfigDict(strict=True)


class ProblemError(BaseModel):
    sku: str
    requested: int = Field(ge=1)
    available: int = Field(ge=0)
    short_by: int = Field(ge=1)


class ValidationProblemError(BaseModel):
    field: str
    message: Annotated[str | None, WithJsonSchema({"type": "string"})] = None
    value: Any = Field(
        default=None,
        json_schema_extra={
            "oneOf": [
                {"type": "string"},
                {"type": "integer"},
                {"type": "number"},
                {"type": "boolean"},
            ]
        },
    )


class Problem(BaseModel):
    type: str
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    trace_id: str = Field(min_length=1)
    # The ``oneOf`` items are installed in ``backend.api.openapi`` because
    # Pydantic validates ``$ref`` values in ``json_schema_extra`` against its
    # own ``$defs`` and would reject a reference to a sibling component.
    errors: Any = None


class StockRow(BaseModel):
    sku: str
    name: str
    on_hand: int = Field(ge=0)
    reserved: int = Field(ge=0)
    available: int = Field(ge=0)
    reorder_point: int = Field(ge=0)
    unit_price_cents: int = Field(ge=0)
    low: bool


class Movement(BaseModel):
    id: UUID
    sku: str
    reason: MovementReason
    delta_on_hand: int
    delta_reserved: int
    actor: str
    note: Annotated[str | None, WithJsonSchema({"type": "string", "nullable": True})]
    order_id: Annotated[
        UUID | None,
        WithJsonSchema({"type": "string", "format": "uuid", "nullable": True}),
    ]
    created_at: datetime
    on_hand_after: int


class OrderLine(BaseModel):
    sku: str
    name: str
    qty: int = Field(ge=1)
    unit_price_cents: int = Field(ge=0)


class Order(BaseModel):
    id: UUID
    customer_ref: str = Field(min_length=3, max_length=40)
    status: OrderStatus
    created_at: datetime
    lines: list[OrderLine] = Field(min_length=1)
    movements: list[Movement]


class Product(BaseModel):
    sku: str
    name: str
    unit_price_cents: int = Field(ge=0)
    reorder_point: int = Field(ge=0)
    available: int = Field(ge=0)
    low: bool


class ReceiveRequest(_StrictModel):
    sku: str
    qty: int = Field(ge=1)
    note: Annotated[str | None, WithJsonSchema({"type": "string"})] = None


class AdjustRequest(_StrictModel):
    sku: str
    delta: int = Field(json_schema_extra={"not": {"enum": [0]}})
    note: str = Field(min_length=1)


class CreateOrderLine(_StrictModel):
    sku: str
    qty: int = Field(ge=1)


class CreateOrderRequest(_StrictModel):
    customer_ref: str = Field(min_length=3, max_length=40)
    lines: list[CreateOrderLine] = Field(min_length=1)


class InvariantViolation(BaseModel):
    rule: str = Field(json_schema_extra={"enum": ["I1", "I2", "I3", "I5"]})
    sku: str
    expected: int
    actual: int
    order_id: Annotated[
        UUID | None,
        WithJsonSchema({"type": "string", "format": "uuid", "nullable": True}),
    ] = None


class InvariantReport(BaseModel):
    ok: bool
    violations: list[InvariantViolation]


class Health(BaseModel):
    status: str = Field(json_schema_extra={"enum": ["ok"]})
    db: str = Field(json_schema_extra={"enum": ["ok", "not_configured"]})


class Version(BaseModel):
    version: str
    commit: str
    build_time: str
    environment: str
