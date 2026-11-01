"""Reservation validation: US1-AC1 at unit level.

``validate_availability`` is pure: it takes locked stock counts and the
requested lines and either returns ``None`` or raises ``InsufficientStock``
naming every short line. No session, no I/O.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from backend.domain import (
    InsufficientStock,
    OrderLine,
    ShortLine,
    StockCounts,
    validate_availability,
)

WAREHOUSE = UUID("00000000-0000-0000-0000-0000000000aa")
ORDER = UUID("00000000-0000-0000-0000-0000000000bb")


def counts(on_hand: int, reserved: int) -> StockCounts:
    return StockCounts(on_hand=on_hand, reserved=reserved)


def line(sku: str = "SKU-1042", qty: int = 2) -> OrderLine:
    return OrderLine(order_id=ORDER, sku=sku, qty=qty)


def test_all_lines_available_returns_none() -> None:
    assert validate_availability([line()], {"SKU-1042": counts(10, 2)}) is None


def test_exact_availability_is_not_short() -> None:
    # Available exactly equals the requested quantity: reservable.
    assert validate_availability([line(qty=8)], {"SKU-1042": counts(8, 0)}) is None


def test_reserved_stock_counts_against_availability() -> None:
    # available = on_hand - reserved, so 10 on hand with 8 reserved leaves 2.
    assert validate_availability([line(qty=2)], {"SKU-1042": counts(10, 8)}) is None


def test_one_short_line_names_it() -> None:
    with pytest.raises(InsufficientStock) as raised:
        validate_availability([line(qty=6)], {"SKU-1042": counts(5, 0)})

    assert raised.value.code == "insufficient_stock"
    assert raised.value.short == [ShortLine(sku="SKU-1042", requested=6, available=5, short_by=1)]


def test_every_short_line_is_named_not_just_the_first() -> None:
    with pytest.raises(InsufficientStock) as raised:
        validate_availability(
            [line("SKU-A", 2), line("SKU-B", 3)],
            {"SKU-A": counts(1, 0), "SKU-B": counts(0, 0)},
        )

    assert {short.sku for short in raised.value.short} == {"SKU-A", "SKU-B"}
    assert raised.value.short[0].short_by == 1  # 2 requested - 1 available
    assert raised.value.short[1].short_by == 3  # 3 requested - 0 available


def test_an_unknown_sku_counts_as_unavailable() -> None:
    # No locked stock row means nothing can be promised.
    with pytest.raises(InsufficientStock) as raised:
        validate_availability([line("SKU-Z", 1)], {})

    assert raised.value.short == [ShortLine(sku="SKU-Z", requested=1, available=0, short_by=1)]


def test_insufficient_stock_message_names_the_skus() -> None:
    try:
        validate_availability([line("SKU-B", 4)], {"SKU-B": counts(1, 0)})
    except InsufficientStock as exc:
        assert "SKU-B" in str(exc)
        assert "No stock was reserved" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("InsufficientStock was not raised")
