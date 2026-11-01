"""QA verification for issue #9 -- independent coverage of the acceptance criteria.

Added by QA in a fresh session. Covers the cases the implementation's own
``tests/integration/test_stock.py`` does not:

- US5-AC1: the persisted counters, not just the response body, move by the
  received quantity, and the configured actor is the one recorded.
- US5-AC2/AC3: the exact boundaries (``on_hand == reserved`` and ``on_hand ==
  0`` are legal) and the precedence when both rejection rules would fire.
- US5-AC4: the API never lets a client pick the ledger reason, and the
  database rejects a reason outside ``receive|adjust|reserve|release|ship``.
- US5-AC5: the route table holds exactly one ``GET`` for the movements path,
  and the contract documents exactly one operation there.
- US6-AC1: ``low`` is exactly ``available <= reorder_point`` for every row,
  including the equality boundary, and the badge clears on receive.
- US6-AC2: the running ``on_hand`` balance is recomputed from the deltas and
  the newest entry equals the current counter.
- US6-AC3: a corrupted *ledger* row (a direct insert, never a mutation through
  the API) and a corrupted *order* row are both reported with ``200``.

All SQL here only reads, except test setup that deliberately corrupts a
disposable database: one direct ``movements`` insert and one direct ``orders``
plus ``order_lines`` insert. No product code is changed and no movement is
updated or deleted.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.config import get_settings
from backend.db import seed as seed_module
from backend.main import app
from tests.integration.test_seed import _fresh_database, _run_alembic

REPO_ROOT = Path(__file__).resolve().parents[2]
MOVEMENT_PATH = "/api/stock/{sku}/movements"
MOVEMENT_REASONS = {"receive", "adjust", "reserve", "release", "ship"}
OPERATOR = "qa-operator"


@pytest.fixture()
def client(database_url: str, monkeypatch: pytest.MonkeyPatch):
    """A TestClient on a fresh, migrated, seeded database (one per test)."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
        monkeypatch.setenv("STOCKROOM_OPERATOR_NAME", OPERATOR)
        get_settings.cache_clear()
        seed_module.seed(engine)
        try:
            with TestClient(app) as test_client:
                yield SimpleNamespace(client=test_client, engine=engine)
        finally:
            get_settings.cache_clear()
            engine.dispose()


def _stock(client, sku: str) -> dict:
    response = client.client.get("/api/stock")
    assert response.status_code == 200
    return next(row for row in response.json() if row["sku"] == sku)


def _movements(client, sku: str) -> list[dict]:
    response = client.client.get(f"/api/stock/{sku}/movements")
    assert response.status_code == 200
    return response.json()


def _snapshot(engine, sku: str) -> tuple[int, int, int, int]:
    """Cached counters, movement count and ledger on-hand sum for one SKU."""
    with engine.connect() as connection:
        counters = connection.execute(
            text("SELECT on_hand, reserved FROM stock WHERE sku = :sku"),
            {"sku": sku},
        ).one()
        movement_count = connection.execute(
            text("SELECT count(*) FROM movements WHERE sku = :sku"),
            {"sku": sku},
        ).scalar_one()
        ledger_on_hand = connection.execute(
            text("SELECT COALESCE(SUM(delta_on_hand), 0) FROM movements WHERE sku = :sku"),
            {"sku": sku},
        ).scalar_one()
    return counters.on_hand, counters.reserved, movement_count, ledger_on_hand


def _warehouse_id(engine) -> uuid.UUID:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT id FROM warehouses WHERE code = 'MAIN'")
        ).scalar_one()


def _flatten_routes(routes):
    """Flatten FastAPI's lazily included routers into the real APIRoutes."""
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _flatten_routes(nested.routes)
        else:
            yield route


def _required_fields(schema_name: str) -> set[str]:
    contract = yaml.safe_load((REPO_ROOT / "openapi.yaml").read_text())
    return set(contract["components"]["schemas"][schema_name]["required"])


def _assert_problem(response, *, status: int, type_: str) -> dict:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == type_
    assert body["status"] == status
    assert body["title"]
    assert body["detail"]
    assert body["trace_id"]
    return body


# --- US5-AC1 ---------------------------------------------------------------


def test_receive_moves_persisted_counters_and_writes_one_actor_stamped_movement(client) -> None:
    before = _stock(client, "SKU-1042")
    note = "QA delivery 9001"

    response = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": 10, "note": note},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["on_hand"] == before["on_hand"] + 10
    assert body["reserved"] == before["reserved"]
    assert body["available"] == before["available"] + 10

    # Read the counters back from the database, not from the response echo.
    persisted = _stock(client, "SKU-1042")
    assert persisted["on_hand"] == before["on_hand"] + 10
    assert persisted["reserved"] == before["reserved"]
    assert persisted["available"] == before["available"] + 10

    with client.engine.connect() as connection:
        movements = connection.execute(
            text(
                "SELECT delta_on_hand, delta_reserved, actor, note, order_id "
                "FROM movements WHERE sku = 'SKU-1042' AND note = :note"
            ),
            {"note": note},
        ).all()

    assert len(movements) == 1
    assert movements[0].delta_on_hand == 10
    assert movements[0].delta_reserved == 0
    assert movements[0].actor == OPERATOR
    assert movements[0].note == note
    assert movements[0].order_id is None

    # The cache moved with exactly one movement and still matches the ledger.
    movement_count, ledger_on_hand = _snapshot(client.engine, "SKU-1042")[2:]
    assert movement_count == 2  # opening receive + this receive
    assert ledger_on_hand == before["on_hand"] + 10
    assert client.client.get("/api/invariants").json() == {"ok": True, "violations": []}


# --- US5-AC2 ---------------------------------------------------------------


def test_adjust_to_exactly_reserved_is_allowed(client) -> None:
    # US5-AC2 forbids on_hand < reserved, so on_hand == reserved is legal.
    order = client.client.post(
        "/api/orders",
        json={"customer_ref": "CUST-QA2", "lines": [{"sku": "SKU-1042", "qty": 5}]},
    )
    assert order.status_code == 201

    response = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -13, "note": "Cycle count to the reservation"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["on_hand"] == 5
    assert body["reserved"] == 5
    assert body["available"] == 0

    on_hand, reserved, movement_count, ledger_on_hand = _snapshot(client.engine, "SKU-1042")
    assert (on_hand, reserved) == (5, 5)
    assert movement_count == 3  # opening receive + reserve + this adjust
    assert ledger_on_hand == 5
    assert client.client.get("/api/invariants").json() == {"ok": True, "violations": []}


def test_adjust_below_reserved_is_rejected_without_any_write(client) -> None:
    order = client.client.post(
        "/api/orders",
        json={"customer_ref": "CUST-QA2", "lines": [{"sku": "SKU-1042", "qty": 5}]},
    )
    assert order.status_code == 201
    before = _snapshot(client.engine, "SKU-1042")

    response = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -14, "note": "Cycle count correction"},
    )

    _assert_problem(response, status=409, type_="would_breach_reserved")
    assert _snapshot(client.engine, "SKU-1042") == before
    assert (before[0], before[1]) == (18, 5)
    assert before[3] == 18  # ledger unchanged too
    assert client.client.get("/api/invariants").json() == {"ok": True, "violations": []}


# --- US5-AC3 ---------------------------------------------------------------


def test_adjust_to_exactly_zero_is_allowed_and_below_zero_is_rejected(client) -> None:
    # US5-AC3 forbids on_hand < 0, so on_hand == 0 is legal.
    response = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -18, "note": "Write off the whole shelf"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["on_hand"] == 0
    assert body["available"] == 0
    on_hand, reserved, movement_count, ledger_on_hand = _snapshot(client.engine, "SKU-1042")
    assert (on_hand, reserved) == (0, 0)
    assert (movement_count, ledger_on_hand) == (2, 0)

    before = _snapshot(client.engine, "SKU-1042")
    rejected = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -1, "note": "One more damaged unit"},
    )
    _assert_problem(rejected, status=409, type_="negative_on_hand")
    assert _snapshot(client.engine, "SKU-1042") == before
    assert before == (0, 0, 2, 0)


def test_negative_on_hand_wins_when_both_rejection_rules_would_fire(client) -> None:
    # 18 on hand with 5 reserved: -19 would be both negative and below the
    # reservation. AC3 says an adjustment below zero is negative_on_hand.
    order = client.client.post(
        "/api/orders",
        json={"customer_ref": "CUST-QA3", "lines": [{"sku": "SKU-1042", "qty": 5}]},
    )
    assert order.status_code == 201
    before = _snapshot(client.engine, "SKU-1042")

    response = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -19, "note": "Impossible correction"},
    )

    _assert_problem(response, status=409, type_="negative_on_hand")
    assert _snapshot(client.engine, "SKU-1042") == before


# --- US5-AC4 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"sku": "SKU-1042", "delta": -1},
        {"sku": "SKU-1042", "delta": -1, "note": ""},
        {"sku": "SKU-1042", "delta": -1, "note": "   "},
    ],
)
def test_adjust_without_a_note_is_a_problem_422_and_writes_nothing(client, payload) -> None:
    before = _snapshot(client.engine, "SKU-1042")

    response = client.client.post("/api/stock/adjust", json=payload)

    _assert_problem(response, status=422, type_="validation_error")
    assert _snapshot(client.engine, "SKU-1042") == before


def test_stock_endpoints_never_let_a_client_choose_the_reason(client) -> None:
    # A caller-supplied reason must not reach the ledger: receive writes
    # 'receive', adjust writes 'adjust', whatever the body claims.
    received = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": 1, "note": "QA", "reason": "teleport"},
    )
    assert received.status_code == 201
    adjusted = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -1, "note": "QA", "reason": "ship"},
    )
    assert adjusted.status_code == 201

    with client.engine.connect() as connection:
        reasons = {
            row.reason
            for row in connection.execute(
                text("SELECT reason FROM movements WHERE sku = 'SKU-1042'")
            ).all()
        }

    assert reasons == {"receive", "adjust"}
    assert reasons <= MOVEMENT_REASONS


def test_the_database_rejects_a_reason_outside_the_domain_set(client) -> None:
    with pytest.raises(IntegrityError) as excinfo, client.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO movements "
                "(id, warehouse_id, sku, delta_on_hand, reason, actor) "
                "VALUES (:id, :warehouse_id, 'SKU-1042', 1, 'teleport', :actor)"
            ),
            {"id": uuid.uuid4(), "warehouse_id": _warehouse_id(client.engine), "actor": OPERATOR},
        )

    assert excinfo.value.orig.diag.constraint_name == "ck_movements_reason"


# --- US5-AC5 ---------------------------------------------------------------


def test_the_movements_path_has_no_mutation_operation(client) -> None:
    contract = yaml.safe_load((REPO_ROOT / "openapi.yaml").read_text())
    assert set(contract["paths"][MOVEMENT_PATH]) == {"get"}

    routes = [
        route
        for route in _flatten_routes(app.routes)
        if getattr(route, "path", None) == MOVEMENT_PATH
    ]
    assert routes
    for route in routes:
        assert set(route.methods or ()) == {"GET"}

    for method in ("put", "patch", "delete"):
        response = client.client.request(method, "/api/stock/SKU-1042/movements")
        assert response.status_code in {404, 405}
        assert response.status_code >= 400


# --- US6-AC1 ---------------------------------------------------------------


def test_every_product_carries_the_contract_fields_and_the_low_predicate(client) -> None:
    products_response = client.client.get("/api/products")
    stock_response = client.client.get("/api/stock")
    assert products_response.status_code == 200
    assert stock_response.status_code == 200
    products = products_response.json()
    stock = stock_response.json()

    required = _required_fields("Product")
    assert required <= set(products[0])
    assert {"sku", "name", "unit_price_cents", "reorder_point", "available", "low"} <= required

    with client.engine.connect() as connection:
        product_count = connection.execute(text("SELECT count(*) FROM products")).scalar_one()
    assert len(products) == product_count
    assert {product["sku"] for product in products} == {row["sku"] for row in stock}

    for product in products:
        assert product["low"] is (product["available"] <= product["reorder_point"])
    for row in stock:
        assert row["available"] == row["on_hand"] - row["reserved"]
        assert row["low"] is (row["available"] <= row["reorder_point"])


def test_low_flag_includes_the_reorder_point_and_clears_on_receive(client) -> None:
    # SKU-1042 has 18 on hand and a reorder point of 6. Adjust down to exactly
    # 6: available == reorder_point, so low is true per US6-AC1 ("<=").
    adjusted = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -12, "note": "Cycle count to the reorder point"},
    )
    assert adjusted.status_code == 201
    assert adjusted.json()["available"] == 6
    assert adjusted.json()["low"] is True

    products = {product["sku"]: product for product in client.client.get("/api/products").json()}
    assert products["SKU-1042"]["available"] == 6
    assert products["SKU-1042"]["reorder_point"] == 6
    assert products["SKU-1042"]["low"] is True

    received = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": 1, "note": "One unit back in stock"},
    )
    assert received.status_code == 201
    assert received.json()["available"] == 7
    assert received.json()["low"] is False

    products = {product["sku"]: product for product in client.client.get("/api/products").json()}
    assert products["SKU-1042"]["available"] == 7
    assert products["SKU-1042"]["low"] is False


# --- US6-AC2 ---------------------------------------------------------------


def test_movements_are_newest_first_with_a_recomputable_running_balance(client) -> None:
    opening = _stock(client, "SKU-1042")["on_hand"]

    received = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": 7, "note": "QA delivery 9002"},
    )
    assert received.status_code == 201
    adjusted = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -2, "note": "QA damage"},
    )
    assert adjusted.status_code == 201
    order = client.client.post(
        "/api/orders",
        json={"customer_ref": "CUST-QA6", "lines": [{"sku": "SKU-1042", "qty": 3}]},
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

    # Recompute the running on-hand balance from the deltas in chronological
    # order; every reported on_hand_after must match it.
    running = 0
    for movement in reversed(movements):
        running += movement["delta_on_hand"]
        assert movement["on_hand_after"] == running
    assert running == _stock(client, "SKU-1042")["on_hand"]
    assert movements[0]["on_hand_after"] == running
    assert movements[-1]["on_hand_after"] == opening

    reserve, adjust, receive, seeded = movements
    assert reserve["order_id"] == order_id
    assert reserve["delta_reserved"] == 3
    assert adjust["order_id"] is None
    assert adjust["note"] == "QA damage"
    assert receive["order_id"] is None
    assert receive["note"] == "QA delivery 9002"
    assert seeded["note"] == seed_module.OPENING_NOTE
    assert all(movement["actor"] == OPERATOR for movement in movements)

    created_at = [movement["created_at"] for movement in movements]
    assert created_at == sorted(created_at, reverse=True)

    required = _required_fields("Movement")
    for movement in movements:
        assert required <= set(movement)
        assert movement["reason"] in MOVEMENT_REASONS


# --- US6-AC3 ---------------------------------------------------------------


def test_invariants_report_a_corrupted_ledger_row_without_a_500(client) -> None:
    # Append-only permits INSERT. Adding a ledger row the cache does not know
    # about is corruption the report must surface rather than crash on.
    warehouse_id = _warehouse_id(client.engine)
    with client.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO movements "
                "(id, warehouse_id, sku, delta_on_hand, reason, actor, note) "
                "VALUES (:id, :warehouse_id, 'SKU-1042', 1, 'receive', :actor, 'corrupt ledger')"
            ),
            {"id": uuid.uuid4(), "warehouse_id": warehouse_id, "actor": OPERATOR},
        )

    response = client.client.get("/api/invariants")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert {
        "rule": "I2",
        "sku": "SKU-1042",
        "expected": 19,
        "actual": 18,
    } in body["violations"]


def test_invariants_report_a_corrupted_order_row_without_a_500(client) -> None:
    # A confirmed order with a line but no reserve movement is I5 corruption.
    order_id = uuid.uuid4()
    warehouse_id = _warehouse_id(client.engine)
    with client.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO orders (id, warehouse_id, customer_ref, status) "
                "VALUES (:id, :warehouse_id, 'CUST-QA7', 'confirmed')"
            ),
            {"id": order_id, "warehouse_id": warehouse_id},
        )
        connection.execute(
            text(
                "INSERT INTO order_lines (order_id, sku, qty, unit_price_cents) "
                "VALUES (:order_id, 'SKU-1042', 2, 129900)"
            ),
            {"order_id": order_id},
        )

    response = client.client.get("/api/invariants")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert {
        "rule": "I5",
        "sku": "SKU-1042",
        "expected": 2,
        "actual": 0,
        "order_id": str(order_id),
    } in body["violations"]


# --- Cross-cutting ---------------------------------------------------------


def test_problem_documents_carry_trace_id_and_problem_json(client) -> None:
    not_found = client.client.get("/api/stock/SKU-NOPE/movements")
    _assert_problem(not_found, status=404, type_="not_found")

    validation = client.client.post("/api/stock/adjust", json={"sku": "SKU-1042", "delta": -1})
    _assert_problem(validation, status=422, type_="validation_error")

    conflict = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -999, "note": "Impossible"},
    )
    _assert_problem(conflict, status=409, type_="negative_on_hand")


def test_responses_carry_every_field_the_contract_requires(client) -> None:
    stock_row = _required_fields("StockRow")
    received = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": 1, "note": "QA shape"},
    )
    assert received.status_code == 201
    assert stock_row <= set(received.json())
    adjusted = client.client.post(
        "/api/stock/adjust",
        json={"sku": "SKU-1042", "delta": -1, "note": "QA shape"},
    )
    assert adjusted.status_code == 201
    assert stock_row <= set(adjusted.json())

    for row in client.client.get("/api/stock").json():
        assert stock_row <= set(row)
    for product in client.client.get("/api/products").json():
        assert _required_fields("Product") <= set(product)
    for movement in _movements(client, "SKU-1042"):
        assert _required_fields("Movement") <= set(movement)
    assert _required_fields("InvariantReport") <= set(client.client.get("/api/invariants").json())


def test_a_movement_written_by_the_stock_api_stays_append_only(client) -> None:
    note = "QA append-only"
    received = client.client.post(
        "/api/stock/receive",
        json={"sku": "SKU-1042", "qty": 1, "note": note},
    )
    assert received.status_code == 201

    with pytest.raises(DBAPIError) as update_error, client.engine.begin() as connection:
        connection.execute(
            text("UPDATE movements SET note = 'tampered' WHERE sku = 'SKU-1042' AND note = :note"),
            {"note": note},
        )
    assert "append-only" in str(update_error.value)

    with pytest.raises(DBAPIError) as delete_error, client.engine.begin() as connection:
        connection.execute(
            text("DELETE FROM movements WHERE sku = 'SKU-1042' AND note = :note"),
            {"note": note},
        )
    assert "append-only" in str(delete_error.value)

    assert any(movement["note"] == note for movement in _movements(client, "SKU-1042"))
