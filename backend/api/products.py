"""The products catalogue view.

``product-spec.md`` §7 ``GET /api/products`` and US6-AC1: every product with its
current availability and the derived low-stock flag. The inventory screen reads
the same fields from ``GET /api/stock``; this endpoint is the catalogue form of
the contract.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.db import models as db_models
from backend.db.session import get_sessionmaker

router = APIRouter()
WAREHOUSE_CODE = "MAIN"


def _warehouse_id(session: Session) -> UUID:
    warehouse_id = session.execute(
        select(db_models.Warehouse.id).where(db_models.Warehouse.code == WAREHOUSE_CODE)
    ).scalar_one_or_none()
    if warehouse_id is None:
        raise RuntimeError(f"no warehouse with code {WAREHOUSE_CODE!r}")
    return warehouse_id


def _product_documents() -> list[dict[str, object]]:
    session = get_sessionmaker()()
    try:
        warehouse_id = _warehouse_id(session)
        rows = session.execute(
            select(db_models.Product, db_models.Stock)
            .outerjoin(
                db_models.Stock,
                and_(
                    db_models.Stock.sku == db_models.Product.sku,
                    db_models.Stock.warehouse_id == warehouse_id,
                ),
            )
            .order_by(db_models.Product.sku)
        ).all()

        documents = []
        for product, stock in rows:
            available = 0 if stock is None else stock.on_hand - stock.reserved
            documents.append(
                {
                    "sku": product.sku,
                    "name": product.name,
                    "unit_price_cents": product.unit_price_cents,
                    "reorder_point": product.reorder_point,
                    "available": available,
                    "low": available <= product.reorder_point,
                }
            )
        return documents
    finally:
        session.close()


@router.get("/api/products")
def list_products() -> JSONResponse:
    """Every product with its availability and low-stock flag (US6-AC1)."""
    return JSONResponse(
        status_code=200,
        media_type="application/json",
        content=_product_documents(),
    )
