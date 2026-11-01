"""Create an order and reserve every line inside one transaction.

``product-spec.md`` US1 (place an order) and US2 (concurrent orders),
``_docs/domain.md`` §3 (ordered ``FOR UPDATE`` reservation).

The handler is the only place stock is written for an order: lock every
touched SKU in ascending order, validate all lines while holding the locks,
then insert the order, its lines and one ``reserve`` movement per line, and
update the cached counters -- all in a single database transaction.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.api.problems import problem, validation_error
from backend.config import get_settings
from backend.db.models import (
    Movement,
    Order,
    Product,
    Stock,
    Warehouse,
)
from backend.db.models import (
    OrderLine as OrderLineModel,
)
from backend.db.session import get_sessionmaker
from backend.domain import InsufficientStock, validate_availability
from backend.domain.movements import OrderLine, reserve_movements
from backend.domain.stock import StockCounts

router = APIRouter()

WAREHOUSE_CODE = "MAIN"


class _UnknownSKU(Exception):
    """An order line references a SKU that does not exist (US1-AC5)."""

    def __init__(self, skus: list[str]) -> None:
        self.skus = list(skus)
        super().__init__(f"Unknown SKU: {', '.join(sorted(skus))}")


def _validate_request(body: object) -> tuple[str, list[tuple[str, int]]] | JSONResponse:
    """Return ``(customer_ref, [(sku, qty), ...])`` or a validation problem."""
    if not isinstance(body, dict):
        return validation_error("Request body must be a JSON object.")

    customer_ref = body.get("customer_ref")
    if not isinstance(customer_ref, str) or not (3 <= len(customer_ref.strip()) <= 40):
        return validation_error("Customer reference must be between 3 and 40 characters.")

    lines = body.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        return validation_error("An order needs at least one line.")

    aggregated: dict[str, int] = {}
    for line in lines:
        if not isinstance(line, dict):
            return validation_error("Each line must be an object with sku and qty.")
        sku = line.get("sku")
        qty = line.get("qty")
        if not isinstance(sku, str) or not sku.strip():
            return validation_error("Each line needs a SKU.")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            return validation_error(f"Quantity for {sku} must be a whole number greater than zero.")
        aggregated[sku] = aggregated.get(sku, 0) + qty

    return customer_ref.strip(), list(aggregated.items())


def _iso(value: datetime) -> str:
    """ISO-8601 UTC with a ``Z`` suffix, matching the contract examples."""
    return value.isoformat().replace("+00:00", "Z")


def _persist_reservation(
    customer_ref: str,
    lines: list[tuple[str, int]],
    actor: str,
) -> dict:
    """Run the reservation transaction and return the order response document.

    Raises :class:`InsufficientStock` when a line cannot be satisfied and
    :class:`_UnknownSKU` when a line names a product that does not exist. In
    both cases the transaction rolls back and nothing is written.
    """
    order_id = uuid.uuid4()
    now = datetime.now(UTC)
    skus = [sku for sku, _ in lines]
    domain_lines = [OrderLine(order_id=order_id, sku=sku, qty=qty) for sku, qty in lines]

    Session = get_sessionmaker()
    session: Session = Session()
    document: dict | None = None
    try:
        session.begin()

        warehouse = session.execute(
            select(Warehouse).where(Warehouse.code == WAREHOUSE_CODE)
        ).scalar_one_or_none()
        if warehouse is None:
            raise RuntimeError(f"no warehouse with code {WAREHOUSE_CODE!r}")
        warehouse_id = warehouse.id

        # Check every SKU exists before taking locks (US1-AC5: client error).
        products = session.execute(select(Product).where(Product.sku.in_(skus))).scalars().all()
        product_by_sku = {product.sku: product for product in products}
        unknown = [sku for sku in skus if sku not in product_by_sku]
        if unknown:
            raise _UnknownSKU(unknown)
        product_info = {
            sku: (product.name, product.unit_price_cents) for sku, product in product_by_sku.items()
        }

        # Lock every touched stock row, ascending SKU, before validating.
        stock_rows = (
            session.execute(
                select(Stock)
                .where(Stock.warehouse_id == warehouse_id, Stock.sku.in_(skus))
                .order_by(Stock.sku)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        stock_by_sku = {row.sku: row for row in stock_rows}
        on_hand_by_sku = {row.sku: row.on_hand for row in stock_rows}

        # US1-AC1: validate every line while holding the locks, name every
        # short line, then roll back so nothing is reserved.
        validate_availability(
            domain_lines,
            {sku: StockCounts(row.on_hand, row.reserved) for sku, row in stock_by_sku.items()},
        )

        order = Order(
            id=order_id,
            warehouse_id=warehouse_id,
            customer_ref=customer_ref,
            status="confirmed",
            created_at=now,
        )
        session.add(order)
        # Flush the order row now so dependent rows (order_lines, movements)
        # can reference its id without an autoflush ordering problem.
        session.flush()

        order_lines = [
            OrderLineModel(
                order_id=order_id,
                sku=line.sku,
                qty=line.qty,
                unit_price_cents=product_info[line.sku][1],
            )
            for line in domain_lines
        ]
        session.add_all(order_lines)

        movements = reserve_movements(
            domain_lines,
            warehouse_id=warehouse_id,
            actor=actor,
            note=f"Order {order_id}",
        )
        movement_orms = [
            Movement(
                id=uuid.uuid4(),
                warehouse_id=m.warehouse_id,
                sku=m.sku,
                delta_on_hand=m.delta_on_hand,
                delta_reserved=m.delta_reserved,
                reason=m.reason,
                order_id=m.order_id,
                actor=m.actor,
                note=m.note,
                created_at=now,
            )
            for m in movements
        ]
        session.add_all(movement_orms)

        # Update the cached counters.
        for line in domain_lines:
            session.execute(
                update(Stock)
                .where(Stock.warehouse_id == warehouse_id, Stock.sku == line.sku)
                .values(reserved=Stock.reserved + line.qty, updated_at=now)
            )

        # Build the response document while the session is still open.
        document = {
            "id": str(order_id),
            "customer_ref": customer_ref,
            "status": "confirmed",
            "created_at": _iso(now),
            "lines": [
                {
                    "sku": line.sku,
                    "name": product_info[line.sku][0],
                    "qty": line.qty,
                    "unit_price_cents": product_info[line.sku][1],
                }
                for line in domain_lines
            ],
            "movements": [
                {
                    "id": str(m.id),
                    "sku": m.sku,
                    "reason": m.reason,
                    "delta_on_hand": m.delta_on_hand,
                    "delta_reserved": m.delta_reserved,
                    "actor": m.actor,
                    "note": m.note,
                    "order_id": str(m.order_id),
                    "created_at": _iso(now),
                    "on_hand_after": on_hand_by_sku[m.sku],
                }
                for m in movement_orms
            ],
        }

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    assert document is not None
    return document


@router.post("/api/orders")
async def create_order(request: Request) -> JSONResponse:
    """Create a ``confirmed`` order and reserve every line in one transaction."""
    body = await request.json()
    validated = _validate_request(body)
    if isinstance(validated, JSONResponse):
        return validated
    customer_ref, lines = validated
    actor = get_settings().operator_name

    try:
        document = await asyncio.to_thread(_persist_reservation, customer_ref, lines, actor)
    except InsufficientStock as exc:
        errors = [
            {
                "sku": short.sku,
                "requested": short.requested,
                "available": short.available,
                "short_by": short.short_by,
            }
            for short in exc.short
        ]
        named = ", ".join(short.sku for short in exc.short)
        count = len(exc.short)
        detail = f"{named} {'is' if count == 1 else 'are'} short. No stock was reserved."
        return problem(
            status_code=status.HTTP_409_CONFLICT,
            type_="insufficient_stock",
            title="Not enough stock",
            detail=detail,
            errors=errors,
        )
    except _UnknownSKU as exc:
        return validation_error(f"Unknown SKU: {', '.join(exc.skus)}")

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        media_type="application/json",
        content=document,
    )
