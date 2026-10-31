"""The database enforces the domain invariants from product-spec I1 and I4."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _seed_warehouse(connection) -> uuid.UUID:
    warehouse_id = uuid.uuid4()
    connection.execute(
        text("INSERT INTO warehouses (id, code) VALUES (:id, :code)"),
        {"id": warehouse_id, "code": _unique("WH")},
    )
    return warehouse_id


def _seed_product(connection, *, unit_price_cents: int = 100) -> tuple[uuid.UUID, str]:
    product_id = uuid.uuid4()
    sku = _unique("SKU")
    connection.execute(
        text(
            "INSERT INTO products (id, sku, name, unit_price_cents) "
            "VALUES (:id, :sku, :name, :price)"
        ),
        {"id": product_id, "sku": sku, "name": "Test product", "price": unit_price_cents},
    )
    return product_id, sku


def _seed_order(
    connection,
    warehouse_id: uuid.UUID,
    *,
    customer_ref: str = "CUST-88",
    status: str = "confirmed",
) -> uuid.UUID:
    order_id = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO orders (id, warehouse_id, customer_ref, status) "
            "VALUES (:id, :warehouse_id, :customer_ref, :status)"
        ),
        {
            "id": order_id,
            "warehouse_id": warehouse_id,
            "customer_ref": customer_ref,
            "status": status,
        },
    )
    return order_id


def _insert_movement(engine: Engine, *, reason: str = "receive") -> uuid.UUID:
    """Insert a warehouse, a product and one opening movement."""
    movement_id = uuid.uuid4()
    with engine.begin() as connection:
        warehouse_id = _seed_warehouse(connection)
        _, sku = _seed_product(connection)
        connection.execute(
            text(
                "INSERT INTO movements "
                "(id, warehouse_id, sku, delta_on_hand, reason, actor) "
                "VALUES (:id, :warehouse_id, :sku, :delta, :reason, :actor)"
            ),
            {
                "id": movement_id,
                "warehouse_id": warehouse_id,
                "sku": sku,
                "delta": 5,
                "reason": reason,
                "actor": "test-operator",
            },
        )
    return movement_id


def _constraint_name(error: IntegrityError) -> str | None:
    return error.orig.diag.constraint_name  # type: ignore[union-attr]


def test_movements_reject_update(engine: Engine, migrated_database: str) -> None:
    movement_id = _insert_movement(engine)

    with pytest.raises(DBAPIError) as excinfo, engine.begin() as connection:
        connection.execute(
            text("UPDATE movements SET note = :note WHERE id = :id"),
            {"note": "tampered", "id": movement_id},
        )

    assert "append-only" in str(excinfo.value)


def test_movements_reject_delete(engine: Engine, migrated_database: str) -> None:
    movement_id = _insert_movement(engine)

    with pytest.raises(DBAPIError) as excinfo, engine.begin() as connection:
        connection.execute(
            text("DELETE FROM movements WHERE id = :id"),
            {"id": movement_id},
        )

    assert "append-only" in str(excinfo.value)


@pytest.mark.parametrize(
    ("on_hand", "reserved", "constraint"),
    [
        (-1, 0, "ck_stock_on_hand_non_negative"),
        (1, -1, "ck_stock_reserved_non_negative"),
        (1, 2, "ck_stock_reserved_le_on_hand"),
    ],
)
def test_stock_checks_reject_invalid_state(
    engine: Engine,
    migrated_database: str,
    on_hand: int,
    reserved: int,
    constraint: str,
) -> None:
    with engine.begin() as connection:
        warehouse_id = _seed_warehouse(connection)
        _, sku = _seed_product(connection)

    with pytest.raises(IntegrityError) as excinfo, engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO stock (warehouse_id, sku, on_hand, reserved) "
                "VALUES (:warehouse_id, :sku, :on_hand, :reserved)"
            ),
            {
                "warehouse_id": warehouse_id,
                "sku": sku,
                "on_hand": on_hand,
                "reserved": reserved,
            },
        )

    assert _constraint_name(excinfo.value) == constraint


def test_products_reject_negative_price(engine: Engine, migrated_database: str) -> None:
    with pytest.raises(IntegrityError) as excinfo, engine.begin() as connection:
        connection.execute(
            text("INSERT INTO products (sku, name, unit_price_cents) VALUES (:sku, :name, :price)"),
            {"sku": _unique("SKU"), "name": "Bad product", "price": -1},
        )

    assert _constraint_name(excinfo.value) == "ck_products_unit_price_cents_non_negative"


@pytest.mark.parametrize(
    ("customer_ref", "status", "constraint"),
    [
        ("ab", "confirmed", "ck_orders_customer_ref_length"),
        ("CUST-88", "pending", "ck_orders_status"),
    ],
)
def test_orders_checks_reject_invalid_state(
    engine: Engine,
    migrated_database: str,
    customer_ref: str,
    status: str,
    constraint: str,
) -> None:
    with engine.begin() as connection:
        warehouse_id = _seed_warehouse(connection)

    with pytest.raises(IntegrityError) as excinfo, engine.begin() as connection:
        _seed_order(
            connection,
            warehouse_id,
            customer_ref=customer_ref,
            status=status,
        )

    assert _constraint_name(excinfo.value) == constraint


def test_order_lines_reject_zero_quantity(
    engine: Engine,
    migrated_database: str,
) -> None:
    with engine.begin() as connection:
        warehouse_id = _seed_warehouse(connection)
        _, sku = _seed_product(connection)
        order_id = _seed_order(connection, warehouse_id)

    with pytest.raises(IntegrityError) as excinfo, engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_lines (order_id, sku, qty, unit_price_cents) "
                "VALUES (:order_id, :sku, :qty, :price)"
            ),
            {"order_id": order_id, "sku": sku, "qty": 0, "price": 100},
        )

    assert _constraint_name(excinfo.value) == "ck_order_lines_qty_positive"


def test_movements_reject_unknown_reason(engine: Engine, migrated_database: str) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        _insert_movement(engine, reason="teleport")

    assert _constraint_name(excinfo.value) == "ck_movements_reason"


def test_order_lines_are_unique_per_order_and_sku(
    engine: Engine,
    migrated_database: str,
) -> None:
    with engine.begin() as connection:
        warehouse_id = _seed_warehouse(connection)
        _, sku = _seed_product(connection)
        order_id = _seed_order(connection, warehouse_id)
        connection.execute(
            text(
                "INSERT INTO order_lines (order_id, sku, qty, unit_price_cents) "
                "VALUES (:order_id, :sku, :qty, :price)"
            ),
            {"order_id": order_id, "sku": sku, "qty": 1, "price": 100},
        )

    with pytest.raises(IntegrityError) as excinfo, engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_lines (order_id, sku, qty, unit_price_cents) "
                "VALUES (:order_id, :sku, :qty, :price)"
            ),
            {"order_id": order_id, "sku": sku, "qty": 2, "price": 100},
        )

    assert _constraint_name(excinfo.value) == "uq_order_lines_order_id_sku"


def test_movements_index_covers_warehouse_sku_created_at_descending(
    engine: Engine,
    migrated_database: str,
) -> None:
    with engine.connect() as connection:
        indexdef = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = 'movements' "
                "AND indexname = :name"
            ),
            {"name": "ix_movements_warehouse_id_sku_created_at"},
        ).scalar_one_or_none()

    assert indexdef is not None
    assert "(warehouse_id, sku, created_at desc)" in indexdef.lower()
