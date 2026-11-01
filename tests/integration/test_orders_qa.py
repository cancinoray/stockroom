"""QA verification for issue #8 -- independent coverage of the acceptance criteria.

Added by QA in a fresh session. Covers the criteria the implementation's own
``tests/integration/test_orders.py`` does not:

- US1-AC3: the line stores the price at order time and a later catalogue
  change does not rewrite it.
- US1-AC1: the short line is named and the other line's ``reserved`` is read
  back explicitly to prove it did not move.
- US2-AC3: ten concurrent orders overlapping on two SKUs, in opposing line
  order, leave every accepted order holding both lines and every rejected
  order holding neither. Run against a live ``uvicorn`` server, not
  ``TestClient`` (``_docs/domain.md`` §5).

All SQL here reads; the only write outside the API is the catalogue price
change of the US1-AC3 scenario, which is product data, not a movement.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.config import get_settings
from backend.db import seed as seed_module
from backend.main import app
from tests.integration.test_seed import _fresh_database, _run_alembic

REPO_ROOT = Path(__file__).resolve().parents[2]

# I2 / I3 from _docs/domain.md §4.
INVARIANT_SQL = """
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

# I5 from _docs/domain.md §4.
UNBALANCED_CONFIRMED_SQL = """
SELECT o.id, l.sku
  FROM orders o
  JOIN order_lines l ON l.order_id = o.id
  LEFT JOIN movements m
         ON m.order_id = o.id AND m.sku = l.sku AND m.reason = 'reserve'
 WHERE o.status = 'confirmed'
 GROUP BY o.id, l.sku, l.qty
HAVING COALESCE(SUM(m.delta_reserved), 0) <> l.qty
"""

SKUS = ("SKU-1042", "SKU-3301")
LINE_ORDERS = (SKUS, tuple(reversed(SKUS)))
QTY_PER_LINE = 4
CONCURRENT_ORDERS = 10


@pytest.fixture()
def seeded_client(database_url: str, monkeypatch: pytest.MonkeyPatch):
    """A TestClient on a fresh, migrated, seeded database (one per test)."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        try:
            seed_module.seed(engine)
            monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
            get_settings.cache_clear()
            with TestClient(app) as client:
                yield SimpleNamespace(client=client, engine=engine)
        finally:
            get_settings.cache_clear()
            engine.dispose()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_live_server(database_url: str) -> tuple[subprocess.Popen[str], str]:
    """Start a real uvicorn server on an ephemeral port and wait for health."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "STOCKROOM_DATABASE_URL": database_url},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"uvicorn exited before becoming ready:\n{stdout}\n{stderr}")
        try:
            with httpx.Client(trust_env=False, timeout=1.0) as http:
                if http.get(f"{base_url}/healthz").status_code == 200:
                    return process, base_url
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    _stop_live_server(process)
    raise AssertionError("uvicorn did not answer /healthz within 30s")


def _stop_live_server(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()


@pytest.fixture()
def live_server(database_url: str):
    """A live uvicorn server over a fresh, migrated, seeded database."""
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        try:
            seed_module.seed(engine)
            process, base_url = _start_live_server(url)
            try:
                yield SimpleNamespace(url=base_url, engine=engine)
            finally:
                _stop_live_server(process)
        finally:
            engine.dispose()


def test_short_line_leaves_the_other_skus_reserved_unchanged(seeded_client) -> None:
    # US1-AC1 wording: "the other SKUs' reserved is unchanged". SKU-1042 has
    # 18 available and is fine on its own; SKU-5127 has 6 and is short by 1.
    response = seeded_client.client.post(
        "/api/orders",
        json={
            "customer_ref": "CUST-QA1",
            "lines": [
                {"sku": "SKU-1042", "qty": 2},
                {"sku": "SKU-5127", "qty": 7},
            ],
        },
    )

    assert response.status_code == 409, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "insufficient_stock"
    assert body["trace_id"]
    assert body["errors"] == [{"sku": "SKU-5127", "requested": 7, "available": 6, "short_by": 1}]

    with seeded_client.engine.connect() as connection:
        reserved = {
            row.sku: row.reserved
            for row in connection.execute(
                text("SELECT sku, reserved FROM stock WHERE sku IN ('SKU-1042', 'SKU-5127')")
            )
        }
        orders = connection.execute(text("SELECT count(*) FROM orders")).scalar_one()
        reserve_movements = connection.execute(
            text("SELECT count(*) FROM movements WHERE reason = 'reserve'")
        ).scalar_one()

    assert reserved == {"SKU-1042": 0, "SKU-5127": 0}
    assert orders == 0
    assert reserve_movements == 0


def test_price_snapshot_survives_a_later_catalogue_change(seeded_client) -> None:
    # US1-AC3: order_lines copies the product price inside the transaction.
    response = seeded_client.client.post(
        "/api/orders",
        json={
            "customer_ref": "CUST-QA3",
            "lines": [
                {"sku": "SKU-1042", "qty": 2},
                {"sku": "SKU-3301", "qty": 3},
            ],
        },
    )
    assert response.status_code == 201, response.text
    response_prices = {line["sku"]: line["unit_price_cents"] for line in response.json()["lines"]}
    assert response_prices == {"SKU-1042": 129_900, "SKU-3301": 28_900}

    # The catalogue changes after the order was placed. Product data is not a
    # movement, so an UPDATE here is allowed; stock counters are untouched.
    with seeded_client.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE products SET unit_price_cents = unit_price_cents + 50000 "
                "WHERE sku IN ('SKU-1042', 'SKU-3301')"
            )
        )

    with seeded_client.engine.connect() as connection:
        catalogue = {
            row.sku: row.unit_price_cents
            for row in connection.execute(text("SELECT sku, unit_price_cents FROM products"))
        }
        stored = {
            row.sku: row.unit_price_cents
            for row in connection.execute(text("SELECT sku, unit_price_cents FROM order_lines"))
        }

    # The catalogue really moved, so the assertion below is meaningful.
    assert catalogue["SKU-1042"] == 179_900
    assert catalogue["SKU-3301"] == 78_900
    # The order kept the prices snapshotted at order time.
    assert stored == {"SKU-1042": 129_900, "SKU-3301": 28_900}


def _order_payload(index: int) -> dict:
    skus = LINE_ORDERS[index % len(LINE_ORDERS)]
    return {
        "customer_ref": f"QA-{index:03d}",
        "lines": [{"sku": sku, "qty": QTY_PER_LINE} for sku in skus],
    }


def test_ten_concurrent_multiline_orders_leave_no_partial_reservation(live_server) -> None:
    # US2-AC3 / I5 / I6. Seed: SKU-1042 has 18 available, SKU-3301 has 40.
    # Every order wants 4 of each, so exactly 4 orders fit on SKU-1042 and
    # SKU-3301 never binds. A non-atomic implementation that reserves one line
    # before failing the other would leave an order partially reserved.
    payloads = [_order_payload(index) for index in range(CONCURRENT_ORDERS)]
    barrier = threading.Barrier(len(payloads))

    def submit(payload: dict) -> httpx.Response:
        with httpx.Client(base_url=live_server.url, timeout=30.0, trust_env=False) as http:
            barrier.wait(timeout=30.0)
            return http.post("/api/orders", json=payload)

    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        responses = list(pool.map(submit, payloads))

    statuses = [response.status_code for response in responses]
    assert set(statuses) <= {201, 409}, statuses
    accepted = [response.json()["id"] for response in responses if response.status_code == 201]
    rejected = [response for response in responses if response.status_code == 409]
    assert len(accepted) == 4, statuses
    assert len(rejected) == 6, statuses

    for response in rejected:
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["type"] == "insufficient_stock"
        assert body["trace_id"]
        assert [error["sku"] for error in body["errors"]] == ["SKU-1042"]

    with live_server.engine.connect() as connection:
        order_rows = connection.execute(text("SELECT id, status FROM orders")).all()
        line_counts = connection.execute(
            text("SELECT order_id, count(*) AS lines FROM order_lines GROUP BY order_id")
        ).all()
        movement_counts = connection.execute(
            text(
                "SELECT order_id, sku, count(*) AS movements, "
                "       SUM(delta_reserved) AS reserved, SUM(delta_on_hand) AS on_hand "
                "  FROM movements WHERE reason = 'reserve' "
                " GROUP BY order_id, sku"
            )
        ).all()
        stock = {
            row.sku: (row.on_hand, row.reserved)
            for row in connection.execute(
                text(
                    "SELECT sku, on_hand, reserved FROM stock WHERE sku IN ('SKU-1042', 'SKU-3301')"
                )
            )
        }
        unbalanced = connection.execute(text(UNBALANCED_CONFIRMED_SQL)).all()
        invariant_violations = connection.execute(text(INVARIANT_SQL)).all()

    # Exactly the accepted orders exist, all confirmed; a rejected order left
    # no order row.
    order_ids = {str(row.id) for row in order_rows}
    assert len(order_rows) == 4
    assert order_ids == set(accepted)
    assert all(row.status == "confirmed" for row in order_rows)

    # Every order holds both lines: no partially reserved order row.
    assert {str(row.order_id): row.lines for row in line_counts} == {
        order_id: 2 for order_id in order_ids
    }

    # I5: one reserve movement per line, of the right size, for both lines.
    movements = {
        (str(row.order_id), row.sku): (row.movements, row.reserved, row.on_hand)
        for row in movement_counts
    }
    assert {order_id for order_id, _ in movements} == order_ids
    assert len(movements) == 8
    for order_id in order_ids:
        for sku in SKUS:
            count, reserved, on_hand = movements[(order_id, sku)]
            assert count == 1
            assert reserved == QTY_PER_LINE
            assert on_hand == 0

    # Counters moved only with the ledger: 4 accepted orders x 4 per SKU.
    assert stock == {"SKU-1042": (18, 16), "SKU-3301": (40, 16)}
    assert unbalanced == []
    assert invariant_violations == []
