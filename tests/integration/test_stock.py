"""Stock endpoints, the invariant report and the catalogue view (issue #9).

Covers US5-AC1 (receive), US5-AC2 (adjust cannot breach reservations),
US5-AC3 (adjust cannot go negative), US5-AC4 (note required on adjust),
US5-AC5 (no movement mutation endpoints), US6-AC1 (``GET /api/products`` and
the ``low`` flag), US6-AC2 (ordered audit trail with a running balance) and
US6-AC3 (invariant report, healthy and corrupted).

Each test gets a disposable, migrated and seeded database, the same harness the
order tests use.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.config import get_settings
from backend.db import seed as seed_module
from backend.main import app
from tests.integration.test_seed import _fresh_database, _run_alembic

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(database_url: str, monkeypatch: pytest.MonkeyPatch):
    """A TestClient on a fresh, migrated, seeded database (one per test)."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
        monkeypatch.setenv("STOCKROOM_OPERATOR_NAME", "demo-operator")
        get_settings.cache_clear()
        seed_module.seed(engine)
        with TestClient(app) as test_client:
            yield SimpleNamespace(client=test_client, engine=engine)
        get_settings.cache_clear()
        engine.dispose()


def _stock_row(client, sku: str) -> dict:
    response = client.client.get("/api/stock")
    assert response.status_code == 200
    return next(row for row in response.json() if row["sku"] == sku)


def _movements(client, sku: str) -> list[dict]:
    response = client.client.get(f"/api/stock/{sku}/movements")
    assert response.status_code == 200
    return response.json()


def _movement_count(client, reason: str) -> int:
    with client.engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM movements WHERE reason = :reason"),
            {"reason": reason},
        ).scalar_one()


def _assert_unchanged(client, sku: str, *, on_hand: int, reserved: int) -> None:
    row = _stock_row(client, sku)
    assert row["on_hand"] == on_hand
    assert row["reserved"] == reserved
    assert row["available"] == on_hand - reserved


def test_list_stock_returns_the_contract_shape(client) -> None:
    response = client.client.get("/api/stock")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 8
    by_sku = {row["sku"]: row for row in rows}

    lamp = by_sku["SKU-1042"]
    assert lamp == {
        "sku": "SKU-1042",
        "name": "Desk lamp, matte black",
        "on_hand": 18,
        "reserved": 0,
        "available": 18,
        "reorder_point": 6,
        "unit_price_cents": 129_900,
        "low": False,
    }

    # SKU-5127 opens at 6 with a reorder point of 10: low, per US6-AC1.
    assert by_sku["SKU-5127"]["available"] == 6
    assert by_sku["SKU-5127"]["reorder_point"] == 10
    assert by_sku["SKU-5127"]["low"] is True


def test_products_returns_catalogue_availability_and_low_flag(client) -> None:
    response = client.client.get("/api/products")

    assert response.status_code == 200
    products = response.json()
    assert len(products) == 8
    by_sku = {product["sku"]: product for product in products}

    expected_fields = {
        "sku",
        "name",
        "unit_price_cents",
        "reorder_point",
        "available",
        "low",
    }
    assert expected_fields <= set(by_sku["SKU-1042"])
    assert by_sku["SKU-1042"]["available"] == 18
    assert by_sku["SKU-1042"]["low"] is False
    assert by_sku["SKU-5127"]["available"] == 6
    assert by_sku["SKU-5127"]["low"] is True


def test_receive_increases_on_hand_and_available_and_writes_one_movement(client) -> None:
    # US5-AC1: receiving 10 units adds 10 to on_hand and available, leaves
    # reserved alone, and records one receive movement with actor and note.
    before = _stock_row(client, "SKU-1042")
    note = "Delivery 4471, supplier invoice 2298"

    response = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": 10, "note": note},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "SKU-1042"
    assert body["on_hand"] == before["on_hand"] + 10
    assert body["reserved"] == before["reserved"]
    assert body["available"] == before["available"] + 10
    assert body["low"] is False

    with client.engine.connect() as connection:
        movements = connection.execute(
            text(
                "SELECT delta_on_hand, delta_reserved, actor, note, order_id "
                "FROM movements WHERE reason = 'receive' AND note = :note"
            ),
            {"note": note},
        ).all()

    assert len(movements) == 1
    movement = movements[0]
    assert movement.delta_on_hand == 10
    assert movement.delta_reserved == 0
    assert movement.actor == get_settings().operator_name
    assert movement.note == note
    assert movement.order_id is None

    # The cache and the ledger still agree after the write.
    assert client.client.get("/api/invariants").json() == {"ok": True, "violations": []}


@pytest.mark.parametrize("qty", [0, -1, 1.5, True, "3"])
def test_receive_rejects_a_quantity_that_is_not_a_positive_integer(client, qty) -> None:
    response = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": qty},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "validation_error"
    assert body["status"] == 422
    assert body["trace_id"]
    assert _movement_count(client, "receive") == 8  # opening movements only


def test_receive_unknown_sku_is_a_404_problem(client) -> None:
    response = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-NOPE", "qty": 1},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["type"] == "not_found"
    assert body["status"] == 404
    assert body["trace_id"]
    assert _movement_count(client, "receive") == 8


def test_adjust_that_would_breach_reservations_is_rejected(client) -> None:
    # US5-AC2: reserve 5 of the 18 on hand, then try to take on_hand below
    # reserved. No movement and no counter changes.
    order = client.client.post(
        "/api/orders",
        json={"customer_ref": "CUST-88", "lines": [{"sku": "SKU-1042", "qty": 5}]},
    )
    assert order.status_code == 201

    response = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -14, "note": "Cycle count correction"},
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "would_breach_reserved"
    assert body["status"] == 409
    assert body["trace_id"]
    assert _movement_count(client, "adjust") == 0
    _assert_unchanged(client, "SKU-1042", on_hand=18, reserved=5)
    assert client.client.get("/api/invariants").json() == {"ok": True, "violations": []}


def test_adjust_below_zero_is_rejected(client) -> None:
    # US5-AC3: 18 on hand, so an adjustment of -19 would go negative. It must
    # be negative_on_hand, not would_breach_reserved (reserved is zero).
    response = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -19, "note": "Damaged in transit"},
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "negative_on_hand"
    assert body["status"] == 409
    assert body["trace_id"]
    assert _movement_count(client, "adjust") == 0
    _assert_unchanged(client, "SKU-1042", on_hand=18, reserved=0)


def test_adjust_writes_one_movement_with_the_note(client) -> None:
    response = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -2, "note": "  Damaged in transit  "},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["on_hand"] == 16
    assert body["available"] == 16
    assert body["reserved"] == 0

    with client.engine.connect() as connection:
        movement = connection.execute(
            text(
                "SELECT delta_on_hand, delta_reserved, actor, note, order_id "
                "FROM movements WHERE reason = 'adjust'"
            )
        ).one()

    assert movement.delta_on_hand == -2
    assert movement.delta_reserved == 0
    assert movement.actor == get_settings().operator_name
    assert movement.note == "Damaged in transit"
    assert movement.order_id is None


@pytest.mark.parametrize(
    "payload",
    [
        {"sku": "SKU-1042", "delta": -1},
        {"sku": "SKU-1042", "delta": -1, "note": ""},
        {"sku": "SKU-1042", "delta": -1, "note": "   "},
        {"sku": "SKU-1042", "delta": -1, "note": None},
        {"sku": "SKU-1042", "delta": -1, "note": 42},
    ],
)
def test_adjust_requires_a_non_empty_note(client, payload) -> None:
    # US5-AC4: adjust needs an explanatory note; blank is a 422 and no write.
    response = client.client.post("/api/stock/adjust", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "validation_error"
    assert body["status"] == 422
    assert body["trace_id"]
    assert _movement_count(client, "adjust") == 0
    _assert_unchanged(client, "SKU-1042", on_hand=18, reserved=0)


@pytest.mark.parametrize("delta", [0, 1.5, True, "2"])
def test_adjust_rejects_a_delta_that_is_not_a_non_zero_integer(client, delta) -> None:
    response = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": delta, "note": "Cycle count correction"},
    )

    assert response.status_code == 422
    assert response.json()["type"] == "validation_error"
    assert _movement_count(client, "adjust") == 0


def test_adjust_unknown_sku_is_a_404_problem(client) -> None:
    response = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-NOPE", "delta": -1, "note": "Cycle count correction"},
    )

    assert response.status_code == 404
    assert response.json()["type"] == "not_found"
    assert _movement_count(client, "adjust") == 0


def test_movements_are_newest_first_with_a_running_on_hand_balance(client) -> None:
    # US6-AC2: receive, adjust, then reserve an order. The trail must be newest
    # first and carry the running on-hand balance, the order reference included.
    opening = _stock_row(client, "SKU-1042")["on_hand"]

    received = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": 5, "note": "Delivery 5001"},
    )
    assert received.status_code == 201
    adjusted = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -2, "note": "Damaged in transit"},
    )
    assert adjusted.status_code == 201
    order = client.client.post(
        "/api/orders",
        json={"customer_ref": "CUST-88", "lines": [{"sku": "SKU-1042", "qty": 2}]},
    )
    assert order.status_code == 201
    order_id = order.json()["id"]

    movements = _movements(client, "SKU-1042")

    assert [movement["reason"] for movement in movements] == [
        "reserve",
        "adjust",
        "receive",
        "receive",
    ]
    assert [movement["on_hand_after"] for movement in movements] == [
        opening + 3,
        opening + 3,
        opening + 5,
        opening,
    ]

    reserve, adjust, receive, seeded = movements
    assert reserve["order_id"] == order_id
    assert reserve["delta_on_hand"] == 0
    assert reserve["delta_reserved"] == 2
    assert adjust["note"] == "Damaged in transit"
    assert adjust["delta_on_hand"] == -2
    assert adjust["order_id"] is None
    assert receive["note"] == "Delivery 5001"
    assert receive["delta_on_hand"] == 5
    assert seeded["note"] == seed_module.OPENING_NOTE
    assert all(movement["actor"] == get_settings().operator_name for movement in movements)

    created_at = [movement["created_at"] for movement in movements]
    assert created_at == sorted(created_at, reverse=True)

    required = {
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
    assert required <= set(reserve)


def test_movements_unknown_sku_is_a_404_problem(client) -> None:
    response = client.client.get("/api/stock/SKU-NOPE/movements")

    assert response.status_code == 404
    assert response.json()["type"] == "not_found"


def test_invariants_are_clean_on_a_healthy_database(client) -> None:
    response = client.client.get("/api/invariants")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "violations": []}


def test_invariants_report_a_corrupted_cache_without_a_500(client) -> None:
    # US6-AC3: a counter that disagrees with the ledger is reported, not hidden.
    with client.engine.begin() as connection:
        connection.execute(text("UPDATE stock SET on_hand = on_hand + 3 WHERE sku = 'SKU-1042'"))

    response = client.client.get("/api/invariants")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert {
        "rule": "I2",
        "sku": "SKU-1042",
        "expected": 18,
        "actual": 21,
    } in body["violations"]


def _routes(routes):
    """Flatten FastAPI's lazily included routers into the real APIRoutes."""
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _routes(nested.routes)
        else:
            yield route


def test_movements_expose_no_mutation_endpoint(client) -> None:
    # US5-AC5: the ledger is read-only over the API, in the route table and in
    # the contract.
    contract = yaml.safe_load((REPO_ROOT / "openapi.yaml").read_text())
    operations = contract["paths"]["/api/stock/{sku}/movements"]
    assert operations.keys() == {"get"}

    routes = [
        route
        for route in _routes(app.routes)
        if getattr(route, "path", None) == "/api/stock/{sku}/movements"
    ]
    assert routes
    for route in routes:
        assert set(route.methods or ()) & {"PUT", "PATCH", "DELETE"} == set()

    for method in ("put", "patch", "delete"):
        response = getattr(client.client, method)("/api/stock/SKU-1042/movements")
        assert response.status_code in {404, 405}
