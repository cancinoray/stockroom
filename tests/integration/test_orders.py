"""Order lifecycle endpoints: create (issue #8) and list/detail/cancel/fulfil (#10).

#8 covers US1-AC1 (short line rejects the whole order), US1-AC2 (successful
order reserves every line), US1-AC4 (invalid quantities), US1-AC5 (unknown
SKU) plus I5 (one reserve movement per line) and I6 (all-or-nothing).

#10 appends US3-AC1..AC3 (cancel releases, double cancel and fulfilled cancel
are 409), US4-AC1/AC3 (fulfil ships both counters, cancelled fulfil is 409),
and ``product-spec.md`` §7: the order list with its ``status`` filter and the
order detail with lines, reservations and the movement timeline.

The issue's proof: ``uv run pytest tests/integration -k orders``.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, create_engine, text

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


def _create_order(client, lines: list[dict], customer_ref: str = "CUST-88") -> dict:
    """Place an order and return its response document."""
    response = _post(client, {"customer_ref": customer_ref, "lines": lines})
    assert response.status_code == 201, response.text
    return response.json()


def _stock(client, *skus: str) -> dict[str, tuple[int, int]]:
    """``{sku: (on_hand, reserved)}`` read straight from the database."""
    with client.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT sku, on_hand, reserved FROM stock WHERE sku IN :skus").bindparams(
                bindparam("skus", expanding=True)
            ),
            {"skus": list(skus)},
        ).all()
    return {row.sku: (row.on_hand, row.reserved) for row in rows}


def _movement_rows(client, order_id: str) -> list:
    """Every ledger row written for one order, oldest first."""
    with client.engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT sku, reason, delta_on_hand, delta_reserved FROM movements "
                "WHERE order_id = :order_id ORDER BY created_at, sku"
            ),
            {"order_id": uuid.UUID(order_id)},
        ).all()


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


def test_cancel_releases_every_line_and_leaves_on_hand(client) -> None:
    # US3-AC1: cancelling a confirmed order writes one release movement per
    # line, returns the reservation and leaves on_hand untouched.
    order = _create_order(
        client,
        [{"sku": "SKU-1042", "qty": 2}, {"sku": "SKU-3301", "qty": 3}],
    )
    assert _stock(client, "SKU-1042", "SKU-3301") == {
        "SKU-1042": (18, 2),
        "SKU-3301": (40, 3),
    }

    response = client.client.post(f"/api/orders/{order['id']}/cancel")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["id"] == order["id"]
    assert body["status"] == "cancelled"

    # Two reserve rows plus two release rows; the release rows are newest.
    assert len(body["movements"]) == 4
    assert [movement["reason"] for movement in body["movements"][:2]] == ["release", "release"]
    releases = {
        movement["sku"]: movement
        for movement in body["movements"]
        if movement["reason"] == "release"
    }
    assert set(releases) == {"SKU-1042", "SKU-3301"}
    assert releases["SKU-1042"]["delta_on_hand"] == 0
    assert releases["SKU-1042"]["delta_reserved"] == -2
    assert releases["SKU-3301"]["delta_on_hand"] == 0
    assert releases["SKU-3301"]["delta_reserved"] == -3

    # Available returns to its prior value; on_hand never moved.
    assert _stock(client, "SKU-1042", "SKU-3301") == {
        "SKU-1042": (18, 0),
        "SKU-3301": (40, 0),
    }

    # One release movement per line, and it is the only one for this order.
    releases_in_db = [row for row in _movement_rows(client, order["id"]) if row.reason == "release"]
    assert sorted((row.sku, row.delta_on_hand, row.delta_reserved) for row in releases_in_db) == [
        ("SKU-1042", 0, -2),
        ("SKU-3301", 0, -3),
    ]


def test_cancel_an_already_cancelled_order_is_409_and_writes_nothing(client) -> None:
    # US3-AC2: cancellation is not idempotent by accident. The second call is
    # refused and writes no second release, so available cannot be inflated.
    order = _create_order(client, [{"sku": "SKU-1042", "qty": 2}])
    assert client.client.post(f"/api/orders/{order['id']}/cancel").status_code == 200
    stock_before = _stock(client, "SKU-1042")
    movements_before = len(_movement_rows(client, order["id"]))

    response = client.client.post(f"/api/orders/{order['id']}/cancel")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "invalid_transition"
    assert body["title"] == "Invalid transition"
    assert body["status"] == 409
    assert body["trace_id"]

    assert _stock(client, "SKU-1042") == stock_before
    rows = _movement_rows(client, order["id"])
    assert len(rows) == movements_before
    assert len([row for row in rows if row.reason == "release"]) == 1


def test_cancel_a_fulfilled_order_is_409_and_changes_no_stock(client) -> None:
    # US3-AC3: fulfilled is terminal for cancellation.
    order = _create_order(client, [{"sku": "SKU-1042", "qty": 2}])
    assert client.client.post(f"/api/orders/{order['id']}/fulfil").status_code == 200
    stock_before = _stock(client, "SKU-1042")
    movements_before = len(_movement_rows(client, order["id"]))

    response = client.client.post(f"/api/orders/{order['id']}/cancel")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "invalid_transition"
    assert response.json()["trace_id"]

    assert _stock(client, "SKU-1042") == stock_before
    rows = _movement_rows(client, order["id"])
    assert len(rows) == movements_before
    assert all(row.reason != "release" for row in rows)


def test_fulfil_ships_both_counters_for_every_line(client) -> None:
    # US4-AC1: one ship movement per line, on_hand and reserved both fall by
    # the line quantity, and the order becomes fulfilled.
    order = _create_order(
        client,
        [{"sku": "SKU-1042", "qty": 2}, {"sku": "SKU-3301", "qty": 3}],
    )

    response = client.client.post(f"/api/orders/{order['id']}/fulfil")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == order["id"]
    assert body["status"] == "fulfilled"

    assert len(body["movements"]) == 4
    assert [movement["reason"] for movement in body["movements"][:2]] == ["ship", "ship"]
    ships = {
        movement["sku"]: movement for movement in body["movements"] if movement["reason"] == "ship"
    }
    assert set(ships) == {"SKU-1042", "SKU-3301"}
    assert (ships["SKU-1042"]["delta_on_hand"], ships["SKU-1042"]["delta_reserved"]) == (-2, -2)
    assert (ships["SKU-3301"]["delta_on_hand"], ships["SKU-3301"]["delta_reserved"]) == (-3, -3)

    assert _stock(client, "SKU-1042", "SKU-3301") == {
        "SKU-1042": (16, 0),
        "SKU-3301": (37, 0),
    }

    ships_in_db = [row for row in _movement_rows(client, order["id"]) if row.reason == "ship"]
    assert sorted((row.sku, row.delta_on_hand, row.delta_reserved) for row in ships_in_db) == [
        ("SKU-1042", -2, -2),
        ("SKU-3301", -3, -3),
    ]


def test_fulfil_a_cancelled_order_is_409_and_changes_no_stock(client) -> None:
    # US4-AC3: a cancelled order cannot be fulfilled.
    order = _create_order(client, [{"sku": "SKU-1042", "qty": 2}])
    assert client.client.post(f"/api/orders/{order['id']}/cancel").status_code == 200
    stock_before = _stock(client, "SKU-1042")
    movements_before = len(_movement_rows(client, order["id"]))

    response = client.client.post(f"/api/orders/{order['id']}/fulfil")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "invalid_transition"
    assert response.json()["trace_id"]

    assert _stock(client, "SKU-1042") == stock_before
    rows = _movement_rows(client, order["id"])
    assert len(rows) == movements_before
    assert all(row.reason != "ship" for row in rows)


def test_concurrent_cancels_release_exactly_once(client) -> None:
    # US3-AC2 under contention: two cancels start together; the order-row lock
    # serialises them, so exactly one succeeds and the release is written once.
    order = _create_order(
        client,
        [{"sku": "SKU-1042", "qty": 2}, {"sku": "SKU-3301", "qty": 3}],
    )
    barrier = threading.Barrier(2)

    def cancel() -> int:
        with TestClient(app) as competing:
            barrier.wait(timeout=10)
            return competing.post(f"/api/orders/{order['id']}/cancel").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _: cancel(), range(2)))

    assert statuses == [200, 409]
    releases = [row for row in _movement_rows(client, order["id"]) if row.reason == "release"]
    assert sorted((row.sku, row.delta_reserved) for row in releases) == [
        ("SKU-1042", -2),
        ("SKU-3301", -3),
    ]
    assert _stock(client, "SKU-1042", "SKU-3301") == {
        "SKU-1042": (18, 0),
        "SKU-3301": (40, 0),
    }


def test_list_orders_filters_by_status_and_is_newest_first(client) -> None:
    # product-spec §7: GET /api/orders returns orders newest first and filters
    # by status; an unknown status is a 422 validation_error.
    confirmed = _create_order(client, [{"sku": "SKU-1042", "qty": 1}], "CUST-A01")
    fulfilled = _create_order(client, [{"sku": "SKU-2087", "qty": 1}], "CUST-A02")
    cancelled = _create_order(client, [{"sku": "SKU-3301", "qty": 1}], "CUST-A03")
    assert client.client.post(f"/api/orders/{fulfilled['id']}/fulfil").status_code == 200
    assert client.client.post(f"/api/orders/{cancelled['id']}/cancel").status_code == 200

    response = client.client.get("/api/orders")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    rows = response.json()
    by_ref = {row["customer_ref"]: row for row in rows}
    assert set(by_ref) == {"CUST-A01", "CUST-A02", "CUST-A03"}
    assert {ref: row["status"] for ref, row in by_ref.items()} == {
        "CUST-A01": "confirmed",
        "CUST-A02": "fulfilled",
        "CUST-A03": "cancelled",
    }
    # Every row carries the list fields, plus the contract's lines and timeline.
    for row in rows:
        assert {"id", "customer_ref", "status", "created_at"} <= set(row)
        assert row["lines"]
        assert row["movements"]
    # Newest first: created_at is never increasing as the list is walked.
    created = [row["created_at"] for row in rows]
    assert created == sorted(created, reverse=True)

    def refs_for(status: str) -> set[str]:
        filtered = client.client.get("/api/orders", params={"status": status})
        assert filtered.status_code == 200
        return {row["customer_ref"] for row in filtered.json()}

    assert refs_for("confirmed") == {"CUST-A01"}
    assert refs_for("fulfilled") == {"CUST-A02"}
    assert refs_for("cancelled") == {"CUST-A03"}
    assert confirmed["status"] == "confirmed"  # the unfiltered create response

    unknown = client.client.get("/api/orders", params={"status": "pending"})
    assert unknown.status_code == 422
    assert unknown.headers["content-type"].startswith("application/problem+json")
    body = unknown.json()
    assert body["type"] == "validation_error"
    assert body["status"] == 422
    assert body["trace_id"]


def test_order_detail_exposes_lines_prices_and_movement_timeline(client) -> None:
    # product-spec §7: GET /api/orders/{id} returns the lines with the price
    # snapshotted at order time, the reservation and the timeline newest first
    # with the real running on-hand balance.
    order = _create_order(
        client,
        [{"sku": "SKU-1042", "qty": 2}, {"sku": "SKU-2087", "qty": 1}],
    )

    response = client.client.get(f"/api/orders/{order['id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == order["id"]
    assert body["customer_ref"] == "CUST-88"
    assert body["status"] == "confirmed"
    assert body["created_at"] == order["created_at"]

    lines = {line["sku"]: line for line in body["lines"]}
    assert set(lines) == {"SKU-1042", "SKU-2087"}
    assert lines["SKU-1042"] == {
        "sku": "SKU-1042",
        "name": "Desk lamp, matte black",
        "qty": 2,
        "unit_price_cents": 129_900,
    }
    assert lines["SKU-2087"] == {
        "sku": "SKU-2087",
        "name": "Task chair, graphite",
        "qty": 1,
        "unit_price_cents": 899_900,
    }

    # The reservation is the reserve movement in the timeline.
    assert len(body["movements"]) == 2
    assert all(movement["reason"] == "reserve" for movement in body["movements"])

    # Fulfilling appends ship rows ahead of the reserve rows and the running
    # balance reflects the whole ledger, not just this order's movements.
    assert client.client.post(f"/api/orders/{order['id']}/fulfil").status_code == 200
    detail = client.client.get(f"/api/orders/{order['id']}").json()
    assert detail["status"] == "fulfilled"
    assert len(detail["movements"]) == 4
    assert [movement["reason"] for movement in detail["movements"][:2]] == ["ship", "ship"]

    timeline = {(movement["sku"], movement["reason"]): movement for movement in detail["movements"]}
    assert timeline[("SKU-1042", "reserve")]["on_hand_after"] == 18
    assert timeline[("SKU-1042", "ship")]["on_hand_after"] == 16
    assert timeline[("SKU-2087", "reserve")]["on_hand_after"] == 10
    assert timeline[("SKU-2087", "ship")]["on_hand_after"] == 9


def test_missing_order_is_404_problem(client) -> None:
    # product-spec §7: an unknown id is a 404 not_found problem document on
    # read and on both transitions, and nothing is written.
    missing = str(uuid.uuid4())
    responses = [
        client.client.get(f"/api/orders/{missing}"),
        client.client.post(f"/api/orders/{missing}/cancel"),
        client.client.post(f"/api/orders/{missing}/fulfil"),
    ]

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["type"] == "not_found"
        assert body["status"] == 404
        assert body["trace_id"]

    with client.engine.connect() as connection:
        movements = connection.execute(
            text("SELECT count(*) FROM movements WHERE reason IN ('release', 'ship')")
        ).scalar_one()
    assert movements == 0
