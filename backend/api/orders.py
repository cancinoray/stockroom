"""Order endpoints: create, list, detail, cancel and fulfil.

``product-spec.md`` US1 (place an order), US2 (concurrent orders), US3
(cancel releases), US4 (fulfil ships) and ``_docs/domain.md`` §2 (ledger rows)
and §3 (ordered ``FOR UPDATE`` writes).

Every order write is one transaction: lock the order row, lock every stock row
the order touches in ascending SKU order, validate while holding the locks, and
write the status change, one movement per line and both cached counters
atomically. Reads never write; they build the contract's ``Order`` document
from the order, its lines and its ledger rows.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Path, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from backend.api.openapi import (
    INSUFFICIENT_STOCK,
    INVALID_TRANSITION,
    NOT_FOUND,
    UNEXPECTED_ERROR,
    VALIDATION_FAILED,
)
from backend.api.problems import problem, validation_error
from backend.api.schemas import CreateOrderRequest
from backend.api.schemas import Order as OrderResponse
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
from backend.domain import (
    InsufficientStock,
    InvalidTransition,
    OrderLine,
    OrderStatus,
    release_movements,
    reserve_movements,
    ship_movements,
    transition,
    validate_availability,
)
from backend.domain.stock import StockCounts

router = APIRouter()

WAREHOUSE_CODE = "MAIN"

# One order's ledger rows, newest first, with the running on-hand balance taken
# over every movement for the same SKU -- not only this order's rows -- so
# ``on_hand_after`` means the same thing here as in the stock audit trail.
_MOVEMENTS_FOR_ORDER = text(
    "WITH ledger AS ("
    "  SELECT id, sku, delta_on_hand, delta_reserved, reason, actor, note, order_id, created_at,"
    "         SUM(delta_on_hand) OVER ("
    "             PARTITION BY sku ORDER BY created_at, id"
    "             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW"
    "         ) AS on_hand_after"
    "    FROM movements"
    "   WHERE warehouse_id = :warehouse_id"
    "     AND sku IN (SELECT sku FROM order_lines WHERE order_id = :order_id)"
    ") "
    "SELECT * FROM ledger WHERE order_id = :order_id "
    "ORDER BY created_at DESC, id DESC"
)


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


def _order_uuid(raw: str) -> uuid.UUID | None:
    """Parse a path parameter, or ``None`` when it cannot be an order id."""
    try:
        return uuid.UUID(raw)
    except (TypeError, ValueError):
        return None


def _order_not_found(order_id: str) -> JSONResponse:
    return problem(
        status_code=status.HTTP_404_NOT_FOUND,
        type_="not_found",
        title="Not found",
        detail=f"Order {order_id} does not exist.",
    )


def _invalid_transition(exc: InvalidTransition) -> JSONResponse:
    return problem(
        status_code=status.HTTP_409_CONFLICT,
        type_="invalid_transition",
        title="Invalid transition",
        detail=f"An order in state '{exc.current}' cannot move to '{exc.target}'.",
    )


def _order_movements(session: Session, order: Order) -> list[dict]:
    """The order's ledger rows, newest first, with ``on_hand_after``."""
    rows = session.execute(
        _MOVEMENTS_FOR_ORDER,
        {"warehouse_id": order.warehouse_id, "order_id": order.id},
    ).mappings()
    return [
        {
            "id": str(row["id"]),
            "sku": row["sku"],
            "reason": row["reason"],
            "delta_on_hand": row["delta_on_hand"],
            "delta_reserved": row["delta_reserved"],
            "actor": row["actor"],
            "note": row["note"],
            "order_id": str(row["order_id"]) if row["order_id"] is not None else None,
            "created_at": _iso(row["created_at"]),
            "on_hand_after": row["on_hand_after"],
        }
        for row in rows
    ]


def _order_document(session: Session, order: Order) -> dict:
    """The contract's ``Order`` shape: header, lines and movement timeline."""
    line_rows = session.execute(
        select(OrderLineModel, Product.name)
        .join(Product, Product.sku == OrderLineModel.sku)
        .where(OrderLineModel.order_id == order.id)
        .order_by(OrderLineModel.sku)
    ).all()
    return {
        "id": str(order.id),
        "customer_ref": order.customer_ref,
        "status": order.status,
        "created_at": _iso(order.created_at),
        "lines": [
            {
                "sku": line.sku,
                "name": name,
                "qty": line.qty,
                "unit_price_cents": line.unit_price_cents,
            }
            for line, name in line_rows
        ],
        "movements": _order_movements(session, order),
    }


def _order_document_by_id(order_id: uuid.UUID) -> dict | None:
    """One order document, or ``None`` when the id does not exist."""
    session = get_sessionmaker()()
    try:
        order = session.get(Order, order_id)
        if order is None:
            return None
        return _order_document(session, order)
    finally:
        session.close()


def _list_order_documents(status: str | None) -> list[dict]:
    """Every order, newest first, optionally filtered by status."""
    session = get_sessionmaker()()
    try:
        query = select(Order).order_by(Order.created_at.desc(), Order.id.desc())
        if status is not None:
            query = query.where(Order.status == status)
        orders = session.execute(query).scalars().all()
        return [_order_document(session, order) for order in orders]
    finally:
        session.close()


def _transition_order(
    order_id: uuid.UUID,
    target: OrderStatus,
    actor: str,
) -> dict | None:
    """Cancel or fulfil one order as a single transaction.

    Locks the order row, then every stock row the order touches in ascending
    SKU order, validates the transition while holding those locks, inserts one
    movement per line and updates both cached counters. Returns ``None`` when
    the order does not exist and raises :class:`InvalidTransition` (after
    rolling back, with nothing written) when the current state forbids the
    move.
    """
    session: Session = get_sessionmaker()()
    document: dict | None = None
    try:
        session.begin()

        # The order row is the serialisation point for its lifecycle: two
        # concurrent cancels take turns, so the second one sees 'cancelled'.
        order = session.execute(
            select(Order).where(Order.id == order_id).with_for_update()
        ).scalar_one_or_none()
        if order is None:
            session.rollback()
            return None

        lines = (
            session.execute(
                select(OrderLineModel)
                .where(OrderLineModel.order_id == order_id)
                .order_by(OrderLineModel.sku)
            )
            .scalars()
            .all()
        )
        skus = [line.sku for line in lines]

        # Lock the stock rows this order touches, ascending SKU (§3).
        stock_rows = (
            session.execute(
                select(Stock)
                .where(Stock.warehouse_id == order.warehouse_id, Stock.sku.in_(skus))
                .order_by(Stock.sku)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        stock_by_sku = {row.sku: row for row in stock_rows}
        missing = [sku for sku in skus if sku not in stock_by_sku]
        if missing:
            raise RuntimeError(
                f"order {order_id} has no stock row for {', '.join(sorted(missing))}"
            )

        # Validate under the locks; a forbidden move raises before any write.
        order.status = transition(order.status, target)

        domain_lines = [OrderLine(order_id=order_id, sku=line.sku, qty=line.qty) for line in lines]
        if target is OrderStatus.CANCELLED:
            movements = release_movements(
                domain_lines, warehouse_id=order.warehouse_id, actor=actor
            )
        else:
            movements = ship_movements(domain_lines, warehouse_id=order.warehouse_id, actor=actor)

        now = datetime.now(UTC)
        session.add_all(
            [
                Movement(
                    id=uuid.uuid4(),
                    warehouse_id=movement.warehouse_id,
                    sku=movement.sku,
                    delta_on_hand=movement.delta_on_hand,
                    delta_reserved=movement.delta_reserved,
                    reason=movement.reason,
                    order_id=movement.order_id,
                    actor=movement.actor,
                    note=movement.note,
                    created_at=now,
                )
                for movement in movements
            ]
        )

        # Cancel returns the reservation; fulfil removes the goods and the hold.
        for line in domain_lines:
            stock = stock_by_sku[line.sku]
            stock.reserved -= line.qty
            if target is OrderStatus.FULFILLED:
                stock.on_hand -= line.qty
            stock.updated_at = now

        session.flush()
        document = _order_document(session, order)
        session.commit()
        return document
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


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


@router.post(
    "/api/orders",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderResponse,
    responses={
        status.HTTP_409_CONFLICT: INSUFFICIENT_STOCK,
        status.HTTP_422_UNPROCESSABLE_ENTITY: VALIDATION_FAILED,
        "default": UNEXPECTED_ERROR,
    },
)
async def create_order(payload: CreateOrderRequest) -> JSONResponse:
    """Create a ``confirmed`` order and reserve every line in one transaction."""
    validated = _validate_request(payload.model_dump())
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


@router.get(
    "/api/orders",
    response_model=list[OrderResponse],
    responses={
        status.HTTP_422_UNPROCESSABLE_ENTITY: VALIDATION_FAILED,
        "default": UNEXPECTED_ERROR,
    },
)
async def list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
) -> JSONResponse:
    """Orders newest first, optionally filtered by status (product-spec §7)."""
    if status_filter is not None and status_filter not in tuple(OrderStatus):
        return validation_error("Unknown order status; expected confirmed, cancelled or fulfilled.")
    documents = await asyncio.to_thread(_list_order_documents, status_filter)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        media_type="application/json",
        content=documents,
    )


@router.get(
    "/api/orders/{id}",
    response_model=OrderResponse,
    responses={status.HTTP_404_NOT_FOUND: NOT_FOUND, "default": UNEXPECTED_ERROR},
)
async def get_order(order_id: str = Path(alias="id")) -> JSONResponse:
    """One order with its lines, reservations and movement timeline (§7)."""
    parsed = _order_uuid(order_id)
    if parsed is None:
        return _order_not_found(order_id)
    document = await asyncio.to_thread(_order_document_by_id, parsed)
    if document is None:
        return _order_not_found(order_id)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        media_type="application/json",
        content=document,
    )


async def _transition_response(order_id: str, target: OrderStatus) -> JSONResponse:
    parsed = _order_uuid(order_id)
    if parsed is None:
        return _order_not_found(order_id)
    try:
        document = await asyncio.to_thread(
            _transition_order,
            parsed,
            target,
            get_settings().operator_name,
        )
    except InvalidTransition as exc:
        return _invalid_transition(exc)
    if document is None:
        return _order_not_found(order_id)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        media_type="application/json",
        content=document,
    )


@router.post(
    "/api/orders/{id}/cancel",
    response_model=OrderResponse,
    responses={
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_409_CONFLICT: INVALID_TRANSITION,
        "default": UNEXPECTED_ERROR,
    },
)
async def cancel_order(order_id: str = Path(alias="id")) -> JSONResponse:
    """Cancel a confirmed order, releasing every line (US3)."""
    return await _transition_response(order_id, OrderStatus.CANCELLED)


@router.post(
    "/api/orders/{id}/fulfil",
    response_model=OrderResponse,
    responses={
        status.HTTP_404_NOT_FOUND: NOT_FOUND,
        status.HTTP_409_CONFLICT: INVALID_TRANSITION,
        "default": UNEXPECTED_ERROR,
    },
)
async def fulfil_order(order_id: str = Path(alias="id")) -> JSONResponse:
    """Fulfil a confirmed order, shipping every line (US4)."""
    return await _transition_response(order_id, OrderStatus.FULFILLED)
