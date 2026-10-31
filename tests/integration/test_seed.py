"""The demo seed is complete, ledger-backed and idempotent.

Each test runs against a database freshly created on the same PostgreSQL server
as the session ``database_url`` fixture. The shared fixture accumulates rows
from the schema tests, and these assertions are about exact counts.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from backend.config import get_settings
from backend.db import seed as seed_module

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_SKUS = {
    "SKU-1042",
    "SKU-2087",
    "SKU-3301",
    "SKU-4410",
    "SKU-5127",
    "SKU-6093",
    "SKU-7714",
    "SKU-8820",
}

# I2 / I3 from _docs/domain.md §4.
INVARIANT_SQL = """
SELECT s.sku,
       s.on_hand            AS cached_on_hand,
       COALESCE(SUM(m.delta_on_hand), 0)  AS ledger_on_hand,
       s.reserved           AS cached_reserved,
       COALESCE(SUM(m.delta_reserved), 0) AS ledger_reserved
  FROM stock s
  LEFT JOIN movements m USING (warehouse_id, sku)
 GROUP BY s.warehouse_id, s.sku, s.on_hand, s.reserved
HAVING s.on_hand  <> COALESCE(SUM(m.delta_on_hand), 0)
    OR s.reserved <> COALESCE(SUM(m.delta_reserved), 0)
    OR s.reserved > s.on_hand
    OR s.on_hand < 0
    OR s.reserved < 0
"""


@contextmanager
def _fresh_database(base_url: str) -> Iterator[str]:
    """Create and drop a database beside the session's disposable one."""
    url = make_url(base_url)
    admin_dsn = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    name = f"stockroom_seed_{uuid.uuid4().hex[:12]}"

    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    try:
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _run_alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "STOCKROOM_DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


@pytest.fixture()
def seed_engine(database_url: str) -> Iterator[Engine]:
    """An empty, migrated database that no other test shares."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    yield
    get_settings.cache_clear()


def _snapshot(engine: Engine) -> dict[str, object]:
    with engine.connect() as connection:
        return {
            "warehouses": connection.execute(text("SELECT count(*) FROM warehouses")).scalar_one(),
            "products": connection.execute(text("SELECT count(*) FROM products")).scalar_one(),
            "movements": connection.execute(text("SELECT count(*) FROM movements")).scalar_one(),
            "counters": connection.execute(
                text("SELECT sku, on_hand, reserved FROM stock ORDER BY sku")
            ).all(),
        }


def test_seed_creates_main_warehouse_and_eight_products(seed_engine: Engine) -> None:
    seed_module.seed(seed_engine)

    with seed_engine.connect() as connection:
        warehouses = connection.execute(text("SELECT code FROM warehouses")).scalars().all()
        products = connection.execute(
            text("SELECT sku, name, unit_price_cents, reorder_point FROM products ORDER BY sku")
        ).all()
        low_stock = connection.execute(
            text(
                "SELECT count(*) FROM stock s JOIN products p USING (sku) "
                "WHERE s.on_hand - s.reserved <= p.reorder_point"
            )
        ).scalar_one()

    assert warehouses == ["MAIN"]
    assert {product.sku for product in products} == EXPECTED_SKUS
    for product in products:
        assert product.name.strip()
        assert isinstance(product.unit_price_cents, int)
        assert product.unit_price_cents >= 0
        assert product.reorder_point > 0
    assert low_stock >= 1


def test_opening_receives_explain_every_on_hand_balance(
    seed_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STOCKROOM_OPERATOR_NAME", "seed-test-operator")
    get_settings.cache_clear()

    seed_module.seed(seed_engine)

    with seed_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT s.sku, s.on_hand, s.reserved, "
                "       COALESCE(SUM(m.delta_on_hand), 0) AS ledger_on_hand, "
                "       COALESCE(SUM(m.delta_reserved), 0) AS ledger_reserved, "
                "       count(m.id) AS opening_movements "
                "  FROM stock s "
                "  JOIN products p USING (sku) "
                "  LEFT JOIN movements m "
                "         ON m.warehouse_id = s.warehouse_id AND m.sku = s.sku "
                "        AND m.reason = 'receive' AND m.note = :note "
                " GROUP BY s.sku, s.on_hand, s.reserved "
                " ORDER BY s.sku"
            ),
            {"note": seed_module.OPENING_NOTE},
        ).all()
        actors = connection.execute(text("SELECT DISTINCT actor FROM movements")).scalars().all()

    assert len(rows) == 8
    for row in rows:
        assert row.on_hand > 0
        assert row.reserved == 0
        assert row.opening_movements == 1
        assert row.ledger_on_hand == row.on_hand
        assert row.ledger_reserved == 0
    assert set(actors) == {"seed-test-operator"}


def test_seed_leaves_the_invariants_clean(seed_engine: Engine) -> None:
    seed_module.seed(seed_engine)

    with seed_engine.connect() as connection:
        violations = connection.execute(text(INVARIANT_SQL)).all()

    assert violations == []


def test_running_the_seed_twice_writes_no_new_rows(seed_engine: Engine) -> None:
    first = seed_module.seed(seed_engine)
    before = _snapshot(seed_engine)

    second = seed_module.seed(seed_engine)
    after = _snapshot(seed_engine)

    assert first.opening_movements_inserted == 8
    assert second.opening_movements_inserted == 0
    assert after == before
    assert after["warehouses"] == 1
    assert after["products"] == 8
    assert after["movements"] == 8


def test_seed_completes_a_partial_previous_state(seed_engine: Engine) -> None:
    actor = get_settings().operator_name

    with seed_engine.begin() as connection:
        warehouse_id = connection.execute(
            text("INSERT INTO warehouses (code) VALUES ('MAIN') RETURNING id")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO products (sku, name, unit_price_cents, reorder_point) "
                "VALUES ('SKU-1042', 'Stale name', 1, 1), ('SKU-2087', 'Stale name', 1, 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO stock (warehouse_id, sku, on_hand, reserved) "
                "VALUES (:warehouse_id, 'SKU-1042', 18, 0)"
            ),
            {"warehouse_id": warehouse_id},
        )
        connection.execute(
            text(
                "INSERT INTO movements "
                "(warehouse_id, sku, delta_on_hand, delta_reserved, reason, actor, note) "
                "VALUES (:warehouse_id, 'SKU-1042', 18, 0, 'receive', :actor, 'Opening count')"
            ),
            {"warehouse_id": warehouse_id, "actor": actor},
        )

    result = seed_module.seed(seed_engine)

    with seed_engine.connect() as connection:
        products = connection.execute(text("SELECT count(*) FROM products")).scalar_one()
        movements = connection.execute(text("SELECT count(*) FROM movements")).scalar_one()
        on_hand = connection.execute(
            text("SELECT on_hand FROM stock WHERE sku = 'SKU-1042'")
        ).scalar_one()
        violations = connection.execute(text(INVARIANT_SQL)).all()

    assert result.opening_movements_inserted == 7
    assert products == 8
    assert movements == 8
    assert on_hand == 18
    assert violations == []
