"""Stock endpoints and the invariant report.

``product-spec.md`` US5 (receive and adjust, with reason), US6 (low stock,
audit trail and invariant report), ``_docs/domain.md`` §2 (ledger semantics) and
§4 (invariant checks).

Every stock write is one transaction: resolve the warehouse, lock the affected
row in ascending SKU order, validate while holding the lock, insert exactly one
movement and update the cached counter. The ledger stays the source of truth.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.api.problems import problem, validation_error
from backend.config import get_settings
from backend.db import models as db_models
from backend.db.session import get_sessionmaker
from backend.domain import MovementReason, check_invariants
from backend.domain.invariants import ORDER_RESERVATION_QUERY, STOCK_LEDGER_QUERY

logger = logging.getLogger(__name__)

router = APIRouter()
WAREHOUSE_CODE = "MAIN"

StockDocument = dict[str, Any]


class _AdjustmentRejected(Exception):
    """A validated adjustment the domain refuses; maps to a 409 problem."""

    def __init__(self, *, type_: str, title: str, detail: str) -> None:
        super().__init__(detail)
        self.type = type_
        self.title = title
        self.detail = detail


def _iso(value: datetime) -> str:
    """ISO-8601 UTC with a ``Z`` suffix, matching the contract examples."""
    return value.isoformat().replace("+00:00", "Z")


def _not_found(sku: str) -> JSONResponse:
    return problem(
        status_code=status.HTTP_404_NOT_FOUND,
        type_="not_found",
        title="Not found",
        detail=f"SKU {sku} does not exist.",
    )


def _stock_document(
    product: db_models.Product,
    *,
    on_hand: int,
    reserved: int,
) -> StockDocument:
    """The ``StockRow`` shape shared by list, receive and adjust."""
    available = on_hand - reserved
    return {
        "sku": product.sku,
        "name": product.name,
        "on_hand": on_hand,
        "reserved": reserved,
        "available": available,
        "reorder_point": product.reorder_point,
        "unit_price_cents": product.unit_price_cents,
        "low": available <= product.reorder_point,
    }


def _warehouse_id(session: Session) -> UUID:
    warehouse_id = session.execute(
        select(db_models.Warehouse.id).where(db_models.Warehouse.code == WAREHOUSE_CODE)
    ).scalar_one_or_none()
    if warehouse_id is None:
        raise RuntimeError(f"no warehouse with code {WAREHOUSE_CODE!r}")
    return warehouse_id


def _product(session: Session, sku: str) -> db_models.Product | None:
    return session.execute(
        select(db_models.Product).where(db_models.Product.sku == sku)
    ).scalar_one_or_none()


def _list_stock_documents() -> list[StockDocument]:
    session = get_sessionmaker()()
    try:
        warehouse_id = _warehouse_id(session)
        rows = session.execute(
            select(db_models.Stock, db_models.Product)
            .join(db_models.Product, db_models.Product.sku == db_models.Stock.sku)
            .where(db_models.Stock.warehouse_id == warehouse_id)
            .order_by(db_models.Stock.sku)
        ).all()
        return [
            _stock_document(product, on_hand=stock.on_hand, reserved=stock.reserved)
            for stock, product in rows
        ]
    finally:
        session.close()


def _receive(sku: str, qty: int, note: str | None, actor: str) -> StockDocument | None:
    """Apply a receive movement and return the updated stock row.

    ``None`` means the product or its stock row does not exist. The movement and
    the counter update commit together, or neither does.
    """
    session = get_sessionmaker()()
    try:
        session.begin()
        warehouse_id = _warehouse_id(session)
        product = _product(session, sku)
        if product is None:
            return None

        stock = session.execute(
            select(db_models.Stock)
            .where(
                db_models.Stock.warehouse_id == warehouse_id,
                db_models.Stock.sku == sku,
            )
            .order_by(db_models.Stock.sku)
            .with_for_update()
        ).scalar_one_or_none()
        if stock is None:
            return None

        now = datetime.now(UTC)
        new_on_hand = stock.on_hand + qty
        session.add(
            db_models.Movement(
                id=uuid.uuid4(),
                warehouse_id=warehouse_id,
                sku=sku,
                delta_on_hand=qty,
                delta_reserved=0,
                reason=MovementReason.RECEIVE,
                actor=actor,
                note=note,
                created_at=now,
            )
        )
        stock.on_hand = new_on_hand
        stock.updated_at = now
        session.commit()
        return _stock_document(product, on_hand=new_on_hand, reserved=stock.reserved)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _adjust(sku: str, delta: int, note: str, actor: str) -> StockDocument | None:
    """Apply a signed adjustment and return the updated stock row.

    ``None`` means the product or its stock row does not exist. Rejections raise
    :class:`_AdjustmentRejected` after the transaction is rolled back, so a
    refused adjustment writes neither a movement nor a counter change.
    """
    session = get_sessionmaker()()
    try:
        session.begin()
        warehouse_id = _warehouse_id(session)
        product = _product(session, sku)
        if product is None:
            return None

        stock = session.execute(
            select(db_models.Stock)
            .where(
                db_models.Stock.warehouse_id == warehouse_id,
                db_models.Stock.sku == sku,
            )
            .order_by(db_models.Stock.sku)
            .with_for_update()
        ).scalar_one_or_none()
        if stock is None:
            return None

        new_on_hand = stock.on_hand + delta
        # US5-AC3 comes first: an adjustment below zero is negative_on_hand even
        # when there are reservations, otherwise every such write would be
        # reported as a reservation breach.
        if new_on_hand < 0:
            raise _AdjustmentRejected(
                type_="negative_on_hand",
                title="Adjustment would make on-hand negative",
                detail=(
                    f"On hand is {stock.on_hand}; an adjustment of {delta} would go below zero."
                ),
            )
        # US5-AC2: on_hand may not drop below what is already promised.
        if new_on_hand < stock.reserved:
            raise _AdjustmentRejected(
                type_="would_breach_reserved",
                title="Adjustment would breach reservations",
                detail=(
                    f"{stock.reserved} units are reserved; on hand cannot drop to {new_on_hand}."
                ),
            )

        now = datetime.now(UTC)
        session.add(
            db_models.Movement(
                id=uuid.uuid4(),
                warehouse_id=warehouse_id,
                sku=sku,
                delta_on_hand=delta,
                delta_reserved=0,
                reason=MovementReason.ADJUST,
                actor=actor,
                note=note,
                created_at=now,
            )
        )
        stock.on_hand = new_on_hand
        stock.updated_at = now
        session.commit()
        return _stock_document(product, on_hand=new_on_hand, reserved=stock.reserved)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _movement_documents(sku: str) -> list[dict[str, Any]] | None:
    """The audit trail for one SKU, newest first, with ``on_hand_after``.

    ``None`` means the SKU does not exist. A known SKU with no movements is an
    empty list.
    """
    session = get_sessionmaker()()
    try:
        warehouse_id = _warehouse_id(session)
        if _product(session, sku) is None:
            return None

        rows = session.execute(
            text(
                "SELECT id, sku, reason, delta_on_hand, delta_reserved, actor, note, "
                "       order_id, created_at, "
                "       SUM(delta_on_hand) OVER ("
                "           ORDER BY created_at, id "
                "           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW"
                "       ) AS on_hand_after "
                "  FROM movements "
                " WHERE warehouse_id = :warehouse_id AND sku = :sku "
                " ORDER BY created_at DESC, id DESC"
            ),
            {"warehouse_id": warehouse_id, "sku": sku},
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
    finally:
        session.close()


def _invariant_report() -> dict[str, Any]:
    """Run the documented checks and serialise the report (US6-AC3).

    Mapping is total in the domain layer, so corrupt data becomes a violation
    entry rather than an exception.
    """
    session = get_sessionmaker()()
    try:
        stock_rows = session.execute(text(STOCK_LEDGER_QUERY)).mappings().all()
        order_rows = session.execute(text(ORDER_RESERVATION_QUERY)).mappings().all()
    finally:
        session.close()

    report = check_invariants(stock_rows=stock_rows, order_rows=order_rows)
    if report.errors:
        logger.warning("Invariant rows could not be mapped: %s", "; ".join(report.errors))

    violations = []
    for violation in report.violations:
        item: dict[str, Any] = {
            "rule": str(violation.rule),
            "sku": violation.sku,
            "expected": violation.expected,
            "actual": violation.actual,
        }
        if violation.order_id is not None:
            item["order_id"] = str(violation.order_id)
        violations.append(item)

    return {"ok": report.ok, "violations": violations}


def _validated_sku(body: dict[str, Any]) -> str | JSONResponse:
    sku = body.get("sku")
    if not isinstance(sku, str) or not sku.strip():
        return validation_error("SKU is required.")
    return sku.strip()


def _validated_note(body: dict[str, Any], *, required: bool) -> str | None | JSONResponse:
    note = body.get("note")
    if note is None:
        if required:
            return validation_error("Note is required for stock adjustments.")
        return None
    if not isinstance(note, str):
        return validation_error("Note must be text.")
    note = note.strip()
    if not note:
        return validation_error("Note is required for stock adjustments.")
    return note


@router.get("/api/stock")
def list_stock() -> JSONResponse:
    """Every stock row for the warehouse, ordered by SKU."""
    return JSONResponse(
        status_code=200, media_type="application/json", content=_list_stock_documents()
    )


@router.post("/api/stock/receive")
async def receive_stock(request: Request) -> JSONResponse:
    """Receive a delivery: one `receive` movement, on_hand increases (US5-AC1)."""
    body = await request.json()
    if not isinstance(body, dict):
        return validation_error("Request body must be a JSON object.")

    sku = _validated_sku(body)
    if isinstance(sku, JSONResponse):
        return sku
    qty = body.get("qty")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
        return validation_error("Quantity must be a whole number greater than zero.")
    note = _validated_note(body, required=False)
    if isinstance(note, JSONResponse):
        return note

    document = await asyncio.to_thread(
        _receive,
        sku,
        qty,
        note,
        get_settings().operator_name,
    )
    if document is None:
        return _not_found(sku)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, media_type="application/json", content=document
    )


@router.post("/api/stock/adjust")
async def adjust_stock(request: Request) -> JSONResponse:
    """Apply a signed adjustment with a required note (US5-AC2..AC4)."""
    body = await request.json()
    if not isinstance(body, dict):
        return validation_error("Request body must be a JSON object.")

    sku = _validated_sku(body)
    if isinstance(sku, JSONResponse):
        return sku
    delta = body.get("delta")
    if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0:
        return validation_error("Adjustment must be a whole number other than zero.")
    note = _validated_note(body, required=True)
    if isinstance(note, JSONResponse):
        return note
    assert isinstance(note, str)

    try:
        document = await asyncio.to_thread(
            _adjust,
            sku,
            delta,
            note,
            get_settings().operator_name,
        )
    except _AdjustmentRejected as exc:
        return problem(
            status_code=status.HTTP_409_CONFLICT,
            type_=exc.type,
            title=exc.title,
            detail=exc.detail,
        )

    if document is None:
        return _not_found(sku)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED, media_type="application/json", content=document
    )


@router.get("/api/stock/{sku}/movements")
async def list_movements(sku: str) -> JSONResponse:
    """The append-only audit trail for one SKU, newest first (US6-AC2)."""
    documents = await asyncio.to_thread(_movement_documents, sku)
    if documents is None:
        return _not_found(sku)
    return JSONResponse(status_code=200, media_type="application/json", content=documents)


@router.get("/api/invariants")
async def get_invariants() -> JSONResponse:
    """Report invariant violations; never fail on corrupt data (US6-AC3)."""
    report = await asyncio.to_thread(_invariant_report)
    return JSONResponse(status_code=200, media_type="application/json", content=report)
