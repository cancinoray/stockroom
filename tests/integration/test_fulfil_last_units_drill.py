"""Drill regression guard (incident stockroom-order-error-rate-high-a697e0be6f0f-1794071189).

An order that takes every remaining available unit of a SKU must still be
fulfillable. The ship lowers `on_hand` and `reserved` together, so the row's
immediate `reserved <= on_hand` check holds at every statement: exactly the
case that fails when the two counters are written separately.
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


def test_a_fulfil_that_takes_every_free_unit_succeeds(client) -> None:
    rows = {row["sku"]: row for row in client.client.get("/api/stock").json()}
    sku = "SKU-8820"
    available = rows[sku]["available"]
    on_hand = rows[sku]["on_hand"]
    assert available > 0

    placed = client.client.post(
        "/api/orders",
        json={"customer_ref": "DRILL-LAST-1", "lines": [{"sku": sku, "qty": available}]},
    )
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["id"]

    fulfilled = client.client.post(f"/api/orders/{order_id}/fulfil")

    assert fulfilled.status_code == 200, fulfilled.text
    assert fulfilled.json()["status"] == "fulfilled"
    assert sorted(m["reason"] for m in fulfilled.json()["movements"]) == ["reserve", "ship"]

    with client.engine.connect() as connection:
        counters = connection.execute(
            text("SELECT on_hand, reserved FROM stock WHERE sku = :sku"), {"sku": sku}
        ).one()
    assert (counters.on_hand, counters.reserved) == (on_hand - available, 0)
    assert client.client.get("/api/invariants").json() == {"ok": True, "violations": []}
