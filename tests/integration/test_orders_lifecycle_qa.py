"""QA verification for issue #10 -- independent lifecycle coverage.

Added by QA in a fresh session. The implementation's ``test_orders.py`` is
left untouched. These tests close the gaps that matter to the issue's
acceptance criteria:

- US3-AC1 / US4-AC1: the exact response document, one movement per line, both
  caches read back from SQL *and* checked against the ledger, every untouched
  SKU compared against a pre-transition snapshot, and ``available`` invariant
  under fulfilment.
- US3-AC2 / US3-AC3 / US4-AC3: ``409 invalid_transition`` as a problem
  document with ``trace_id``, with the whole ``stock`` table and the global
  movement count unchanged.
- ``product-spec.md`` §7 list: empty list, status filters that match nothing,
  required row fields, and unknown status as a ``422`` problem.
- ``product-spec.md`` §7 detail: snapshotted ``unit_price_cents`` after a
  catalogue price change, reserve/release movements as the reservation
  record, newest-first timeline with ``on_hand_after``, and ``404`` problems
  for a missing or malformed id.

All SQL here only reads, except the single product-catalogue price update in
the snapshot test, which is product data rather than a ledger movement. No
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

ORDER_REQUIRED = {"id", "customer_ref", "status", "created_at", "lines", "movements"}
ORDER_LINE_REQUIRED = {"sku", "name", "qty", "unit_price_cents"}
MOVEMENT_REQUIRED = {
    "id",
    "sku",
    "reason",
    "delta_on_hand",
    "delta_reserved",
    "actor",
    "note",
    "order_id",
    "created_at",
    "on_hand_after",
}

# I2 / I3 from _docs/domain.md §4: caches must equal the ledger.
CACHE_LEDGER_SQL = """
SELECT s.sku
  FROM stock s
  LEFT JOIN movements m USING (warehouse_id, sku)
 GROUP BY s.warehouse_id, s.sku, s.on_hand, s.reserved
HAVING s.on_hand  <> COALESCE(SUM(m.delta_on_hand), 0)
    OR s.reserved <> COALESCE(SUM(m.delta_reserved), 0)
    OR s.reserved > s.on_hand
    OR s.on_hand < 0
    OR s.reserved < 0
"""


@pytest.fixture()
def qa_client(database_url: str, monkeypatch: pytest.MonkeyPatch):
    """A TestClient on a fresh, migrated, seeded database (one per test)."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        try:
            seed_module.seed(engine)
            monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
            get_settings.cache_clear()
            with TestClient(app) as test_client:
                yield SimpleNamespace(client=test_client, engine=engine)
        finally:
            get_settings.cache_clear()
            engine.dispose()


def _create_order(qa_client, lines: list[dict], customer_ref: str = "CUST-QA1") -> dict:
    response = qa_client.client.post(
        "/api/orders", json={"customer_ref": customer_ref, "lines": lines}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _all_counters(qa_client) -> dict[str, tuple[int, int]]:
    """``{sku: (on_hand, reserved)}`` for every stock row, read from SQL."""
    with qa_client.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT sku, on_hand, reserved FROM stock ORDER BY sku")
        ).all()
    return {row.sku: (row.on_hand, row.reserved) for row in rows}


def _movement_count(qa_client, order_id: str | None = None) -> int:
    query = "SELECT count(*) FROM movements"
    params: dict[str, object] = {}
    if order_id is not None:
        query += " WHERE order_id = :order_id"
        params["order_id"] = uuid.UUID(order_id)
    with qa_client.engine.connect() as connection:
        return int(connection.execute(text(query), params).scalar_one())


def _movements_for_order(qa_client, order_id: str) -> list:
    with qa_client.engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT sku, reason, delta_on_hand, delta_reserved FROM movements "
                "WHERE order_id = :order_id ORDER BY created_at, sku"
            ),
            {"order_id": uuid.UUID(order_id)},
        ).all()


def _cache_ledger_violations(qa_client) -> list[str]:
    with qa_client.engine.connect() as connection:
        return [row.sku for row in connection.execute(text(CACHE_LEDGER_SQL))]


def _assert_problem(response, *, status: int, type_: str) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == type_
    assert body["status"] == status
    assert body["title"]
    assert body["detail"]
    assert body["trace_id"]
    return body


def _assert_order_shape(document: dict) -> None:
    assert set(document) >= ORDER_REQUIRED
    assert document["status"] in {"confirmed", "cancelled", "fulfilled"}
    assert document["lines"]
    for line in document["lines"]:
        assert set(line) >= ORDER_LINE_REQUIRED
    for movement in document["movements"]:
        assert set(movement) >= MOVEMENT_REQUIRED


def test_cancel_returns_exact_ledger_and_leaves_every_other_sku_alone(qa_client) -> None:
    # US3-AC1: 200 cancelled, one release per line, available restored,
    # on_hand unchanged, one transaction, and no unrelated stock touched.
    order = _create_order(
        qa_client,
        [{"sku": "SKU-1042", "qty": 2}, {"sku": "SKU-3301", "qty": 3}],
    )
    before = _all_counters(qa_client)
    movements_before = _movement_count(qa_client)

    response = qa_client.client.post(f"/api/orders/{order['id']}/cancel")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    _assert_order_shape(body)
    assert body["id"] == order["id"]
    assert body["customer_ref"] == order["customer_ref"]
    assert body["status"] == "cancelled"
    assert body["created_at"] == order["created_at"]

    # One release row per line, with the domain table's exact deltas.
    rows = _movements_for_order(qa_client, order["id"])
    releases = [row for row in rows if row.reason == "release"]
    assert len(releases) == 2
    assert sorted((row.sku, row.delta_on_hand, row.delta_reserved) for row in releases) == [
        ("SKU-1042", 0, -2),
        ("SKU-3301", 0, -3),
    ]
    # The transaction wrote exactly those two rows and nothing else.
    assert _movement_count(qa_client) - movements_before == 2
    assert _movement_count(qa_client, order["id"]) == 4  # two reserves + two releases

    after = _all_counters(qa_client)
    # The reservation is returned and on_hand did not move, so available
    # (on_hand - reserved) is back to its pre-order value.
    assert after["SKU-1042"] == (before["SKU-1042"][0], 0)
    assert after["SKU-3301"] == (before["SKU-3301"][0], 0)
    assert after["SKU-1042"][0] == before["SKU-1042"][0]
    assert after["SKU-3301"][0] == before["SKU-3301"][0]
    # Every other SKU is byte-for-byte unchanged.
    assert {sku: after[sku] for sku in after if sku not in {"SKU-1042", "SKU-3301"}} == {
        sku: before[sku] for sku in before if sku not in {"SKU-1042", "SKU-3301"}
    }
    # Both caches still equal the ledger after the transition.
    assert _cache_ledger_violations(qa_client) == []


def test_fulfil_returns_exact_ledger_and_keeps_availability(qa_client) -> None:
    # US4-AC1 (+ US4-AC2 as a cross-check): 200 fulfilled, one ship per line
    # with -q on both deltas, both counters reduced, available unchanged, no
    # unrelated stock touched.
    order = _create_order(
        qa_client,
        [{"sku": "SKU-1042", "qty": 2}, {"sku": "SKU-3301", "qty": 3}],
    )
    before = _all_counters(qa_client)
    movements_before = _movement_count(qa_client)

    response = qa_client.client.post(f"/api/orders/{order['id']}/fulfil")

    assert response.status_code == 200, response.text
    body = response.json()
    _assert_order_shape(body)
    assert body["id"] == order["id"]
    assert body["status"] == "fulfilled"

    rows = _movements_for_order(qa_client, order["id"])
    ships = [row for row in rows if row.reason == "ship"]
    assert len(ships) == 2
    assert sorted((row.sku, row.delta_on_hand, row.delta_reserved) for row in ships) == [
        ("SKU-1042", -2, -2),
        ("SKU-3301", -3, -3),
    ]
    assert _movement_count(qa_client) - movements_before == 2
    assert _movement_count(qa_client, order["id"]) == 4

    after = _all_counters(qa_client)
    assert after["SKU-1042"] == (before["SKU-1042"][0] - 2, 0)
    assert after["SKU-3301"] == (before["SKU-3301"][0] - 3, 0)
    # available = on_hand - reserved is identical before and after.
    for sku in ("SKU-1042", "SKU-3301"):
        assert (after[sku][0] - after[sku][1]) == (before[sku][0] - before[sku][1])
    assert {sku: after[sku] for sku in after if sku not in {"SKU-1042", "SKU-3301"}} == {
        sku: before[sku] for sku in before if sku not in {"SKU-1042", "SKU-3301"}
    }
    assert _cache_ledger_violations(qa_client) == []


def test_double_cancel_is_409_and_changes_no_counter_or_ledger(qa_client) -> None:
    # US3-AC2: the second cancel is a problem+json 409 and writes nothing.
    order = _create_order(
        qa_client,
        [{"sku": "SKU-1042", "qty": 2}, {"sku": "SKU-3301", "qty": 3}],
    )
    assert qa_client.client.post(f"/api/orders/{order['id']}/cancel").status_code == 200
    counters_before = _all_counters(qa_client)
    movements_before = _movement_count(qa_client)

    body = _assert_problem(
        qa_client.client.post(f"/api/orders/{order['id']}/cancel"),
        status=409,
        type_="invalid_transition",
    )
    assert body["title"] == "Invalid transition"

    assert _all_counters(qa_client) == counters_before
    assert _movement_count(qa_client) == movements_before
    # The order stayed cancelled and no second release exists.
    detail = qa_client.client.get(f"/api/orders/{order['id']}").json()
    assert detail["status"] == "cancelled"
    assert (
        len(
            [row for row in _movements_for_order(qa_client, order["id"]) if row.reason == "release"]
        )
        == 2
    )


def test_invalid_terminal_transitions_are_409_and_write_nothing(qa_client) -> None:
    # US3-AC3 (cancel a fulfilled order) and US4-AC3 (fulfil a cancelled
    # order), plus a repeated fulfil. Every attempt is a 409 problem with a
    # trace id, zero new movements, and no counter change anywhere.
    fulfilled = _create_order(qa_client, [{"sku": "SKU-1042", "qty": 1}], "CUST-QA2")
    cancelled = _create_order(qa_client, [{"sku": "SKU-3301", "qty": 2}], "CUST-QA3")
    assert qa_client.client.post(f"/api/orders/{fulfilled['id']}/fulfil").status_code == 200
    assert qa_client.client.post(f"/api/orders/{cancelled['id']}/cancel").status_code == 200

    cases = [
        (f"/api/orders/{fulfilled['id']}/cancel", fulfilled["id"]),
        (f"/api/orders/{fulfilled['id']}/fulfil", fulfilled["id"]),
        (f"/api/orders/{cancelled['id']}/fulfil", cancelled["id"]),
    ]
    for path, order_id in cases:
        counters_before = _all_counters(qa_client)
        movements_before = _movement_count(qa_client)
        order_rows_before = len(_movements_for_order(qa_client, order_id))

        _assert_problem(
            qa_client.client.post(path),
            status=409,
            type_="invalid_transition",
        )

        assert _all_counters(qa_client) == counters_before
        assert _movement_count(qa_client) == movements_before
        assert len(_movements_for_order(qa_client, order_id)) == order_rows_before
    # The orders remain in their terminal states.
    assert qa_client.client.get(f"/api/orders/{fulfilled['id']}").json()["status"] == "fulfilled"
    assert qa_client.client.get(f"/api/orders/{cancelled['id']}").json()["status"] == "cancelled"


def test_list_empty_filters_and_unknown_status(qa_client) -> None:
    # product-spec §7: an empty list is 200 [], a filter with no matches is
    # 200 [], an unknown status is a 422 problem, and each row carries the
    # list fields.
    empty = qa_client.client.get("/api/orders")
    assert empty.status_code == 200
    assert empty.headers["content-type"].startswith("application/json")
    assert empty.json() == []

    for status in ("confirmed", "cancelled", "fulfilled"):
        filtered = qa_client.client.get("/api/orders", params={"status": status})
        assert filtered.status_code == 200
        assert filtered.json() == []

    unknown = _assert_problem(
        qa_client.client.get("/api/orders", params={"status": "pending"}),
        status=422,
        type_="validation_error",
    )
    assert unknown["status"] == 422

    confirmed = _create_order(qa_client, [{"sku": "SKU-1042", "qty": 1}], "CUST-QA4")
    cancelled = _create_order(qa_client, [{"sku": "SKU-3301", "qty": 1}], "CUST-QA5")
    assert qa_client.client.post(f"/api/orders/{cancelled['id']}/cancel").status_code == 200

    rows = qa_client.client.get("/api/orders").json()
    assert {row["customer_ref"] for row in rows} == {"CUST-QA4", "CUST-QA5"}
    for row in rows:
        assert {"id", "customer_ref", "status", "created_at"} <= set(row)
        _assert_order_shape(row)

    confirmed_rows = qa_client.client.get("/api/orders", params={"status": "confirmed"}).json()
    assert {row["id"] for row in confirmed_rows} == {confirmed["id"]}
    assert all(row["status"] == "confirmed" for row in confirmed_rows)

    cancelled_rows = qa_client.client.get("/api/orders", params={"status": "cancelled"}).json()
    assert {row["id"] for row in cancelled_rows} == {cancelled["id"]}
    assert all(row["status"] == "cancelled" for row in cancelled_rows)

    # A valid status that matches nothing is an empty list, not an error.
    fulfilled_rows = qa_client.client.get("/api/orders", params={"status": "fulfilled"}).json()
    assert fulfilled_rows == []


def test_detail_snapshot_reservation_timeline_and_missing_id(qa_client) -> None:
    # product-spec §7: the detail keeps the line price that was snapshotted at
    # order time even after the catalogue changes, exposes the reservation
    # movement, returns the timeline newest first with on_hand_after, and a
    # missing (or malformed) id is a 404 problem.
    order = _create_order(qa_client, [{"sku": "SKU-1042", "qty": 2}])
    original_price = order["lines"][0]["unit_price_cents"]

    # Catalogue data changes after the order; the snapshot must not move.
    with qa_client.engine.begin() as connection:
        connection.execute(
            text("UPDATE products SET unit_price_cents = :price WHERE sku = :sku"),
            {"price": original_price + 10_000, "sku": "SKU-1042"},
        )

    response = qa_client.client.get(f"/api/orders/{order['id']}")
    assert response.status_code == 200, response.text
    detail = response.json()
    _assert_order_shape(detail)
    assert detail["id"] == order["id"]
    assert detail["customer_ref"] == order["customer_ref"]
    assert detail["status"] == "confirmed"
    assert detail["created_at"] == order["created_at"]

    assert len(detail["lines"]) == 1
    line = detail["lines"][0]
    assert line["sku"] == "SKU-1042"
    assert line["qty"] == 2
    assert line["unit_price_cents"] == original_price
    assert line["name"] == "Desk lamp, matte black"

    # The reservation is the reserve row, with the order reference and the
    # running on-hand balance the stock audit trail uses.
    reservations = [m for m in detail["movements"] if m["reason"] == "reserve"]
    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation["sku"] == "SKU-1042"
    assert reservation["delta_on_hand"] == 0
    assert reservation["delta_reserved"] == 2
    assert reservation["order_id"] == order["id"]
    assert reservation["on_hand_after"] == 18
    assert reservation["actor"]

    # Cancelling appends release rows ahead of the reservation; timeline is
    # newest first and every row carries on_hand_after.
    assert qa_client.client.post(f"/api/orders/{order['id']}/cancel").status_code == 200
    after_cancel = qa_client.client.get(f"/api/orders/{order['id']}").json()
    assert after_cancel["status"] == "cancelled"
    _assert_order_shape(after_cancel)
    reasons = [movement["reason"] for movement in after_cancel["movements"]]
    assert reasons == ["release", "reserve"]
    created = [movement["created_at"] for movement in after_cancel["movements"]]
    assert created == sorted(created, reverse=True)
    release = after_cancel["movements"][0]
    assert (release["delta_on_hand"], release["delta_reserved"]) == (0, -2)
    assert release["on_hand_after"] == 18
    # The line kept its snapshot after the transition too.
    assert after_cancel["lines"][0]["unit_price_cents"] == original_price

    missing = str(uuid.uuid4())
    for order_id in (missing, "not-a-uuid"):
        _assert_problem(
            qa_client.client.get(f"/api/orders/{order_id}"),
            status=404,
            type_="not_found",
        )
