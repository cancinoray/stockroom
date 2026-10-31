"""Availability and low stock: US4-AC2, US6-AC1.

``available = on_hand - reserved`` is the number the operator acts on, so it is
computed in one place and the low-stock rule reads it rather than a raw balance.
"""

from uuid import UUID

import pytest

from backend.domain import (
    Movement,
    MovementReason,
    OrderLine,
    StockCounts,
    release_movements,
    reserve_movements,
    ship_movements,
)

WAREHOUSE = UUID("00000000-0000-0000-0000-0000000000aa")
ORDER = UUID("00000000-0000-0000-0000-0000000000bb")
ACTOR = "demo-operator"


def counts(on_hand: int, reserved: int) -> StockCounts:
    return StockCounts(on_hand=on_hand, reserved=reserved)


def line(sku: str = "SKU-1042", qty: int = 2) -> OrderLine:
    return OrderLine(order_id=ORDER, sku=sku, qty=qty)


def test_available_is_on_hand_minus_reserved() -> None:
    assert counts(on_hand=10, reserved=4).available == 6


@pytest.mark.parametrize(
    ("on_hand", "reserved", "reorder_point", "low"),
    [
        (10, 4, 5, False),  # available 6 > 5
        (10, 4, 6, True),  # available 6 <= 6: the boundary is low (US6-AC1)
        (1, 1, 0, True),  # available 0 <= 0
        (0, 0, 0, True),
        (5, 0, 4, False),
    ],
)
def test_low_stock_compares_available_with_the_reorder_point(
    on_hand: int,
    reserved: int,
    reorder_point: int,
    low: bool,
) -> None:
    assert counts(on_hand, reserved).is_low(reorder_point) is low


def test_fulfilment_leaves_availability_unchanged() -> None:
    # US4-AC2: the goods were already promised, so shipping changes both
    # counters by the same amount.
    before = counts(on_hand=10, reserved=3)

    after = before.apply_all(ship_movements([line(qty=3)], warehouse_id=WAREHOUSE, actor=ACTOR))

    assert after.available == before.available
    assert after == counts(on_hand=7, reserved=0)


def test_reserving_lowers_availability_and_releasing_restores_it() -> None:
    start = counts(on_hand=10, reserved=0)

    reserved = start.apply_all(
        reserve_movements([line(qty=2)], warehouse_id=WAREHOUSE, actor=ACTOR)
    )
    released = reserved.apply_all(
        release_movements([line(qty=2)], warehouse_id=WAREHOUSE, actor=ACTOR)
    )

    assert reserved.available == 8
    assert released.available == start.available
    assert released == start


def test_receiving_clears_the_low_stock_flag() -> None:
    low = counts(on_hand=1, reserved=0)
    assert low.is_low(reorder_point=2) is True

    receive = Movement(
        warehouse_id=WAREHOUSE,
        sku="SKU-1042",
        delta_on_hand=5,
        delta_reserved=0,
        reason=MovementReason.RECEIVE,
        order_id=None,
        actor=ACTOR,
    )

    assert low.apply(receive).is_low(reorder_point=2) is False
