"""Idempotent demo seed data for Stockroom.

One warehouse (``MAIN``), eight products taken from the frontend mock, and one
opening ``receive`` movement per product. The counters in ``stock`` are derived
from those movements inside the same transaction; nothing here hand-writes a
counter (``AGENTS.md`` rules 1 and 3).

The whole seed is one transaction and takes a transaction-scoped advisory lock,
so a failed run leaves nothing behind and two concurrent runs cannot both write
opening balances. The opening movements themselves are the idempotency marker:
a product that already has a ``receive`` movement with the ``Opening count``
note is left alone, which also makes a partially seeded database converge
without duplicating rows.

The seed only adds rows. It does not delete warehouses, products or movements
that exist outside its own set; ``make reset`` is the destructive path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Engine, bindparam, text
from sqlalchemy.engine import Connection

from backend.config import get_settings
from backend.db.session import get_engine

WAREHOUSE_CODE = "MAIN"
OPENING_NOTE = "Opening count"

# "STOCKROO" as a fixed 64-bit key. Advisory locks are released when the
# transaction ends, so the lock cannot leak on a failed run.
_SEED_LOCK_KEY = 0x53544F434B524F4F


@dataclass(frozen=True)
class SeedProduct:
    sku: str
    name: str
    unit_price_cents: int
    reorder_point: int
    opening_on_hand: int


# Kept in ascending SKU order. The values mirror frontend/src/api/mock.ts so
# the demo data and the prototype tell the same story; SKU-5127 and SKU-7714
# open at or below their reorder points, which makes low stock demoable.
SEED_PRODUCTS: tuple[SeedProduct, ...] = (
    SeedProduct("SKU-1042", "Desk lamp, matte black", 129_900, 6, 18),
    SeedProduct("SKU-2087", "Task chair, graphite", 899_900, 4, 10),
    SeedProduct("SKU-3301", "A4 copy paper, 500 sheets", 28_900, 20, 40),
    SeedProduct("SKU-4410", "Monitor arm, single", 349_900, 3, 5),
    SeedProduct("SKU-5127", "Cable tray, 1 metre", 74_900, 10, 6),
    SeedProduct("SKU-6093", "Storage bin, 15 litre", 45_900, 8, 27),
    SeedProduct("SKU-7714", "Packing tape, 50 metre", 12_900, 14, 12),
    SeedProduct("SKU-8820", "Label printer, thermal", 1_249_900, 2, 3),
)

_SEEDED_SKUS = [product.sku for product in SEED_PRODUCTS]


@dataclass(frozen=True)
class SeedResult:
    warehouse_id: uuid.UUID
    products: int
    opening_movements_inserted: int


def seed(engine: Engine | None = None, *, operator_name: str | None = None) -> SeedResult:
    """Insert the demo data if it is missing and return what was written.

    ``operator_name`` defaults to ``settings.operator_name``. Callers that use
    the configured database can omit ``engine``; tests pass a disposable one.
    """
    actor = operator_name or get_settings().operator_name
    target = engine or get_engine()

    with target.begin() as connection:
        return _seed(connection, actor=actor)


def _seed(connection: Connection, *, actor: str) -> SeedResult:
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _SEED_LOCK_KEY},
    )

    warehouse_id = _ensure_warehouse(connection)
    _ensure_products(connection)
    _ensure_stock_rows(connection, warehouse_id)
    _lock_stock_rows(connection, warehouse_id)
    inserted = _apply_opening_balances(connection, warehouse_id, actor=actor)
    _assert_caches_match_ledger(connection, warehouse_id)

    return SeedResult(
        warehouse_id=warehouse_id,
        products=len(SEED_PRODUCTS),
        opening_movements_inserted=inserted,
    )


def _ensure_warehouse(connection: Connection) -> uuid.UUID:
    connection.execute(
        text("INSERT INTO warehouses (code) VALUES (:code) ON CONFLICT (code) DO NOTHING"),
        {"code": WAREHOUSE_CODE},
    )
    return connection.execute(
        text("SELECT id FROM warehouses WHERE code = :code"),
        {"code": WAREHOUSE_CODE},
    ).scalar_one()


def _ensure_products(connection: Connection) -> None:
    connection.execute(
        text(
            "INSERT INTO products (sku, name, unit_price_cents, reorder_point, active) "
            "VALUES (:sku, :name, :unit_price_cents, :reorder_point, true) "
            "ON CONFLICT (sku) DO UPDATE SET "
            "    name = EXCLUDED.name, "
            "    unit_price_cents = EXCLUDED.unit_price_cents, "
            "    reorder_point = EXCLUDED.reorder_point, "
            "    active = true"
        ),
        [
            {
                "sku": product.sku,
                "name": product.name,
                "unit_price_cents": product.unit_price_cents,
                "reorder_point": product.reorder_point,
            }
            for product in SEED_PRODUCTS
        ],
    )


def _ensure_stock_rows(connection: Connection, warehouse_id: uuid.UUID) -> None:
    connection.execute(
        text(
            "INSERT INTO stock (warehouse_id, sku, on_hand, reserved) "
            "VALUES (:warehouse_id, :sku, 0, 0) "
            "ON CONFLICT (warehouse_id, sku) DO NOTHING"
        ),
        [{"warehouse_id": warehouse_id, "sku": product.sku} for product in SEED_PRODUCTS],
    )


def _lock_stock_rows(connection: Connection, warehouse_id: uuid.UUID) -> None:
    """Lock the seeded rows in ascending SKU order, as rule 2 requires."""
    connection.execute(
        text(
            "SELECT sku FROM stock "
            "WHERE warehouse_id = :warehouse_id AND sku IN :skus "
            "ORDER BY sku "
            "FOR UPDATE"
        ).bindparams(bindparam("skus", expanding=True)),
        {"warehouse_id": warehouse_id, "skus": _SEEDED_SKUS},
    )


def _apply_opening_balances(
    connection: Connection,
    warehouse_id: uuid.UUID,
    *,
    actor: str,
) -> int:
    already_opened = set(
        connection.execute(
            text(
                "SELECT sku FROM movements "
                "WHERE warehouse_id = :warehouse_id "
                "  AND reason = 'receive' "
                "  AND note = :note "
                "  AND sku IN :skus"
            ).bindparams(bindparam("skus", expanding=True)),
            {
                "warehouse_id": warehouse_id,
                "note": OPENING_NOTE,
                "skus": _SEEDED_SKUS,
            },
        ).scalars()
    )

    inserted = 0
    for product in SEED_PRODUCTS:
        if product.sku in already_opened:
            continue

        connection.execute(
            text(
                "INSERT INTO movements "
                "(warehouse_id, sku, delta_on_hand, delta_reserved, reason, actor, note) "
                "VALUES (:warehouse_id, :sku, :delta_on_hand, 0, 'receive', :actor, :note)"
            ),
            {
                "warehouse_id": warehouse_id,
                "sku": product.sku,
                "delta_on_hand": product.opening_on_hand,
                "actor": actor,
                "note": OPENING_NOTE,
            },
        )
        connection.execute(
            text(
                "UPDATE stock "
                "SET on_hand = on_hand + :delta_on_hand, updated_at = now() "
                "WHERE warehouse_id = :warehouse_id AND sku = :sku"
            ),
            {
                "warehouse_id": warehouse_id,
                "sku": product.sku,
                "delta_on_hand": product.opening_on_hand,
            },
        )
        inserted += 1

    return inserted


def _assert_caches_match_ledger(connection: Connection, warehouse_id: uuid.UUID) -> None:
    """Refuse to commit a seed whose caches disagree with the ledger.

    This is a report, not a repair: rule 3 says drift is surfaced, never
    hand-fixed. Raising rolls the whole seed back.
    """
    violations = connection.execute(
        text(
            "SELECT s.sku, s.on_hand, s.reserved, "
            "       COALESCE(SUM(m.delta_on_hand), 0)  AS ledger_on_hand, "
            "       COALESCE(SUM(m.delta_reserved), 0) AS ledger_reserved "
            "  FROM stock s "
            "  LEFT JOIN movements m USING (warehouse_id, sku) "
            " WHERE s.warehouse_id = :warehouse_id AND s.sku IN :skus "
            " GROUP BY s.warehouse_id, s.sku, s.on_hand, s.reserved "
            "HAVING s.on_hand  <> COALESCE(SUM(m.delta_on_hand), 0) "
            "    OR s.reserved <> COALESCE(SUM(m.delta_reserved), 0) "
            "    OR s.reserved > s.on_hand "
            "    OR s.on_hand < 0 "
            "    OR s.reserved < 0"
        ).bindparams(bindparam("skus", expanding=True)),
        {"warehouse_id": warehouse_id, "skus": _SEEDED_SKUS},
    ).all()

    if violations:
        detail = ", ".join(
            f"{row.sku} cached={row.on_hand}/{row.reserved} "
            f"ledger={row.ledger_on_hand}/{row.ledger_reserved}"
            for row in violations
        )
        raise RuntimeError(f"seed aborted: stock caches disagree with the ledger: {detail}")


def main() -> None:
    result = seed()
    print(
        f"seed: warehouse {WAREHOUSE_CODE}, {result.products} products, "
        f"{result.opening_movements_inserted} new opening movements"
    )


if __name__ == "__main__":
    main()
