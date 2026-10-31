"""The database enforces the domain invariants from product-spec I1 and I4."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _insert_movement(engine: Engine) -> uuid.UUID:
    """Insert a warehouse, a product and one opening movement."""
    suffix = uuid.uuid4().hex[:10]
    warehouse_id = uuid.uuid4()
    product_id = uuid.uuid4()
    movement_id = uuid.uuid4()
    sku = f"SKU-{suffix}"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO warehouses (id, code) VALUES (:id, :code)"),
            {"id": warehouse_id, "code": _unique("WH")},
        )
        connection.execute(
            text(
                "INSERT INTO products (id, sku, name, unit_price_cents) "
                "VALUES (:id, :sku, :name, :price)"
            ),
            {"id": product_id, "sku": sku, "name": "Test product", "price": 100},
        )
        connection.execute(
            text(
                "INSERT INTO movements "
                "(id, warehouse_id, sku, delta_on_hand, actor) "
                "VALUES (:id, :warehouse_id, :sku, :delta, :actor)"
            ),
            {
                "id": movement_id,
                "warehouse_id": warehouse_id,
                "sku": sku,
                "delta": 5,
                "actor": "test-operator",
            },
        )
    return movement_id


def test_movements_reject_update(engine: Engine, migrated_database: str) -> None:
    movement_id = _insert_movement(engine)

    with pytest.raises(DBAPIError) as excinfo:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE movements SET note = :note WHERE id = :id"),
                {"note": "tampered", "id": movement_id},
            )

    assert "append-only" in str(excinfo.value)


def test_movements_reject_delete(engine: Engine, migrated_database: str) -> None:
    movement_id = _insert_movement(engine)

    with pytest.raises(DBAPIError) as excinfo:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM movements WHERE id = :id"),
                {"id": movement_id},
            )

    assert "append-only" in str(excinfo.value)
