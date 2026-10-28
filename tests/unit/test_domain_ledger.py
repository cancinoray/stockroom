"""Movement writer: I5 and the ledger table in _docs/domain.md §2.

The writer is pure: it takes order lines plus the warehouse/actor an API handler
already knows, and returns movement rows ready to insert. No session, no I/O.
"""

from collections.abc import Callable
from uuid import UUID

import pytest

from backend.domain import (
    InvalidQuantity,
    Movement,
    MovementReason,
    OrderLine,
    release_movements,
    reserve_movements,
    ship_movements,
)

WAREHOUSE = UUID("00000000-0000-0000-0000-0000000000aa")
ORDER = UUID("00000000-0000-0000-0000-0000000000bb")
ACTOR = "demo-operator"


def line(sku: str = "SKU-1042", qty: int = 3) -> OrderLine:
    return OrderLine(order_id=ORDER, sku=sku, qty=qty)


@pytest.mark.parametrize(
    ("factory", "reason", "delta_on_hand", "delta_reserved"),
    [
        (reserve_movements, MovementReason.RESERVE, 0, 3),
        (release_movements, MovementReason.RELEASE, 0, -3),
        (ship_movements, MovementReason.SHIP, -3, -3),
    ],
)
def test_order_line_movements_match_the_ledger_table(
    factory: Callable[..., tuple[Movement, ...]],
    reason: MovementReason,
    delta_on_hand: int,
    delta_reserved: int,
) -> None:
    (movement,) = factory([line()], warehouse_id=WAREHOUSE, actor=ACTOR)

    assert movement == Movement(
        warehouse_id=WAREHOUSE,
        sku="SKU-1042",
        delta_on_hand=delta_on_hand,
        delta_reserved=delta_reserved,
        reason=reason,
        order_id=ORDER,
        actor=ACTOR,
        note=None,
    )


def test_reserve_carries_a_positive_reserved_delta() -> None:
    # I5: delta_reserved == +qty, and a reservation never moves on_hand.
    (movement,) = reserve_movements([line(qty=4)], warehouse_id=WAREHOUSE, actor=ACTOR)

    assert movement.delta_reserved == 4
    assert movement.delta_on_hand == 0


def test_every_line_gets_exactly_one_movement() -> None:
    movements = reserve_movements(
        [line("SKU-A", 1), line("SKU-B", 2)],
        warehouse_id=WAREHOUSE,
        actor=ACTOR,
    )

    assert len(movements) == 2
    assert {movement.sku for movement in movements} == {"SKU-A", "SKU-B"}


def test_movements_are_ordered_by_sku() -> None:
    # The transaction locks in ascending SKU order; writing rows in the same
    # order keeps a trace readable.
    movements = ship_movements(
        [line("SKU-C", 1), line("SKU-A", 2), line("SKU-B", 1)],
        warehouse_id=WAREHOUSE,
        actor=ACTOR,
    )

    assert [movement.sku for movement in movements] == ["SKU-A", "SKU-B", "SKU-C"]


def test_order_movements_reference_the_order_and_carry_no_note() -> None:
    (movement,) = release_movements([line()], warehouse_id=WAREHOUSE, actor=ACTOR)

    assert movement.order_id == ORDER
    assert movement.note is None


@pytest.mark.parametrize("qty", [0, -1])
def test_a_non_positive_quantity_is_rejected(qty: int) -> None:
    # order_lines.qty has check (qty > 0); the writer refuses it before SQL does.
    with pytest.raises(InvalidQuantity):
        line(qty=qty)


def test_movement_reasons_are_the_database_check_values() -> None:
    assert {reason.value for reason in MovementReason} == {
        "receive",
        "adjust",
        "reserve",
        "release",
        "ship",
    }
