"""``POST /api/orders`` reserves every line inside one transaction (issue #8).

Covers US1-AC1 (short line rejects the whole order), US1-AC2 (successful
order reserves every line), US1-AC4 (invalid quantities), US1-AC5 (unknown
SKU) plus I5 (one reserve movement per line) and I6 (all-or-nothing).

The three ``-k reserve`` tests are the issue's proof:
``make test-integration -k reserve`` -> 3 passed.
"""

from __future__ import annotations

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
    """A TestClient pointed at a fresh, migrated, seeded database per test."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        seed_module.seed(engine)
        monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
        get_settings.cache_clear()
        with TestClient(app) as test_client:
            yield SimpleNamespace(client=test_client, engine=engine)
        get_settings.cache_clear()


def _post(client, payload: dict):
    return client.client.post("/api/orders", json=payload)


def test_reserve_rejects_a_short_line_and_reserves_nothing(client) -> None:
    # US1-AC1: SKU-5127 has 6 available; asking for 7 rejects the whole order
    # even though SKU-1042 is plentiful. No order row, no reservation.
    response = _post(
        client,
        {
            "customer_ref": "CUST-88",
            "lines": [
                {"sku": "SKU-1042", "qty": 1},
                {"sku": "SKU-5127", "qty": 7},
            ],
        },
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "insufficient_stock"
    assert body["title"] == "Not enough stock"
    assert body["status"] == 409
    assert body["trace_id"]
    assert body["errors"] == [{"sku": "SKU-5127", "requested": 7, "available": 6, "short_by": 1}]

    # Nothing was written: no order row and reserved is unchanged.
    with client.engine.connect() as connection:
        orders = connection.execute(text("SELECT count(*) FROM orders")).scalar_one()
        reserved = connection.execute(
            text("SELECT reserved FROM stock WHERE sku = :sku"), {"sku": "SKU-5127"}
        ).scalar_one()
        movements = connection.execute(
            text("SELECT count(*) FROM movements WHERE reason = 'reserve'")
        ).scalar_one()

    assert orders == 0
    assert reserved == 0
    assert movements == 0


def test_reserve_successful_order_reserves_every_line(client) -> None:
    # US1-AC2: all lines available -> 201 confirmed, available drops per line,
    # one reserve movement per line with the price snapshotted, counters updated.
    response = _post(
        client,
        {
            "customer_ref": "CUST-88",
            "lines": [
                {"sku": "SKU-1042", "qty": 2},
                {"sku": "SKU-2087", "qty": 1},
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["customer_ref"] == "CUST-88"
    by_sku = {line["sku"]: line for line in body["lines"]}
    assert set(by_sku) == {"SKU-1042", "SKU-2087"}
    assert by_sku["SKU-1042"]["unit_price_cents"] == 129_900  # SKU-1042 snapshot
    assert by_sku["SKU-2087"]["unit_price_cents"] == 899_900  # SKU-2087 snapshot
    assert len(body["movements"]) == 2
    assert all(movement["reason"] == "reserve" for movement in body["movements"])
    assert all(movement["delta_on_hand"] == 0 for movement in body["movements"])
    assert all(movement["delta_reserved"] > 0 for movement in body["movements"])

    # Cached counters updated, one order row, invariants still clean.
    with client.engine.connect() as connection:
        reserved_1042 = connection.execute(
            text("SELECT reserved FROM stock WHERE sku = 'SKU-1042'")
        ).scalar_one()
        reserved_2087 = connection.execute(
            text("SELECT reserved FROM stock WHERE sku = 'SKU-2087'")
        ).scalar_one()
        orders = connection.execute(text("SELECT count(*) FROM orders")).scalar_one()
        movements = connection.execute(
            text("SELECT count(*) FROM movements WHERE reason = 'reserve'")
        ).scalar_one()

    assert reserved_1042 == 2
    assert reserved_2087 == 1
    assert orders == 1
    assert movements == 2

    # I5 / I6: one confirmed order, exactly one reserve movement per line,
    # and the counters agree with the ledger.
    with client.engine.connect() as connection:
        ledger = connection.execute(
            text(
                "SELECT sku, SUM(delta_reserved) AS reserved_sum "
                "FROM movements WHERE reason = 'reserve' GROUP BY sku"
            )
        ).all()
        ledger_by_sku = {row.sku: row.reserved_sum for row in ledger}
    assert ledger_by_sku == {"SKU-1042": 2, "SKU-2087": 1}


def test_reserve_unknown_sku_is_a_client_error(client) -> None:
    # US1-AC5: an unknown SKU is a 422 validation_error naming the SKU, not a 500.
    response = _post(
        client,
        {"customer_ref": "CUST-88", "lines": [{"sku": "SKU-NOPE", "qty": 1}]},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "validation_error"
    assert body["status"] == 422
    assert body["trace_id"]
    assert "SKU-NOPE" in body["detail"]

    # Nothing written.
    with client.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM orders")).scalar_one() == 0


def test_invalid_quantity_is_rejected_with_422(client) -> None:
    # US1-AC4: zero or negative quantities are rejected and reserve nothing.
    for qty in (0, -1):
        response = _post(
            client,
            {"customer_ref": "CUST-88", "lines": [{"sku": "SKU-1042", "qty": qty}]},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["type"] == "validation_error"
        assert body["status"] == 422

    with client.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM orders")).scalar_one() == 0
        assert (
            connection.execute(
                text("SELECT reserved FROM stock WHERE sku = 'SKU-1042'")
            ).scalar_one()
            == 0
        )


def test_duplicate_lines_aggregate_to_one_line(client) -> None:
    # Duplicate lines for the same SKU are aggregated before reservation.
    response = _post(
        client,
        {
            "customer_ref": "CUST-88",
            "lines": [
                {"sku": "SKU-1042", "qty": 1},
                {"sku": "SKU-1042", "qty": 2},
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["lines"]) == 1
    assert body["lines"][0]["sku"] == "SKU-1042"
    assert body["lines"][0]["qty"] == 3
