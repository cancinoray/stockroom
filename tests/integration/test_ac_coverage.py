"""T4.2 coverage audit: the one AC clause no existing test asserted.

Every clause in issue #39's AC list already has a passing integration test
except one. US1-AC2 says "available drops by the ordered quantity *for each
line*". ``test_reserve_successful_order_reserves_every_line`` reads only
``reserved`` back from SQL, and every other test that reads stock after a
reservation does so either for a single line (the adjust tests) or as raw
``on_hand``/``reserved`` columns (the cancel tests). No test read the API's
``available`` for each line of a successful multi-line order, so a reservation
that moved the wrong line's availability, or none at all, could pass.

The case below is the only addition; the PR carries the AC -> test matrix for
the rest. It reuses the session ``database_url`` fixture and the per-test
fresh-database pattern from ``test_seed.py`` -- no second harness, and no
movement is ever updated or deleted.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.config import get_settings
from backend.db import seed as seed_module
from backend.main import app
from tests.integration.test_seed import _fresh_database, _run_alembic


@pytest.fixture()
def client(database_url: str, monkeypatch: pytest.MonkeyPatch):
    """A TestClient on a fresh, migrated, seeded database (one per test)."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        try:
            monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
            get_settings.cache_clear()
            seed_module.seed(engine)
            with TestClient(app) as test_client:
                yield SimpleNamespace(client=test_client, engine=engine)
        finally:
            get_settings.cache_clear()
            engine.dispose()


def _stock_rows(client, *skus: str) -> dict[str, dict]:
    """``{sku: /api/stock row}``, read through the API from the persisted caches."""
    response = client.client.get("/api/stock")
    assert response.status_code == 200
    rows = {row["sku"]: row for row in response.json()}
    return {sku: rows[sku] for sku in skus}


def test_successful_order_drops_available_by_the_ordered_quantity_per_line(client) -> None:
    # US1-AC2. The quantities differ per line, so applying one line's quantity
    # to both lines cannot pass.
    lines = {"SKU-1042": 2, "SKU-3301": 3}
    before = _stock_rows(client, *lines)
    assert {sku: row["available"] for sku, row in before.items()} == {
        "SKU-1042": 18,
        "SKU-3301": 40,
    }

    response = client.client.post(
        "/api/orders",
        json={
            "customer_ref": "CUST-AC2",
            "lines": [{"sku": sku, "qty": qty} for sku, qty in lines.items()],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "confirmed"

    after = _stock_rows(client, *lines)
    for sku, qty in lines.items():
        # on_hand does not move, the line's reservation does, so available
        # falls by exactly this line's ordered quantity.
        assert after[sku]["on_hand"] == before[sku]["on_hand"]
        assert after[sku]["reserved"] == before[sku]["reserved"] + qty
        assert after[sku]["available"] == before[sku]["available"] - qty
        assert after[sku]["available"] == after[sku]["on_hand"] - after[sku]["reserved"]

    # The drop is backed by exactly one reserve movement per line, read back
    # from the ledger rather than from the create response.
    with client.engine.connect() as connection:
        movements = connection.execute(
            text(
                "SELECT sku, delta_on_hand, delta_reserved FROM movements "
                "WHERE reason = 'reserve' AND order_id = :order_id ORDER BY sku"
            ),
            {"order_id": uuid.UUID(response.json()["id"])},
        ).all()

    assert [(row.sku, row.delta_on_hand, row.delta_reserved) for row in movements] == [
        ("SKU-1042", 0, 2),
        ("SKU-3301", 0, 3),
    ]
