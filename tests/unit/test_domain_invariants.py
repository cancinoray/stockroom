"""Invariant queries and row mapping: I2, I3, I5 (_docs/domain.md §4).

The checker never touches a session. It exposes the documented SQL and turns the
rows a caller fetched into violations. A check that raises is worse than no
check, so malformed input becomes an error entry, not an exception.
"""

from uuid import UUID

from backend.domain import (
    ORDER_RESERVATION_QUERY,
    STOCK_LEDGER_QUERY,
    InvariantRule,
    Violation,
    check_invariants,
    order_violations,
    stock_violations,
)

ORDER_ID = UUID("00000000-0000-0000-0000-0000000000bb")


def stock_row(
    *,
    sku: str = "SKU-1042",
    cached_on_hand: int = 7,
    ledger_on_hand: int = 7,
    cached_reserved: int = 2,
    ledger_reserved: int = 2,
) -> dict[str, object]:
    return {
        "sku": sku,
        "cached_on_hand": cached_on_hand,
        "ledger_on_hand": ledger_on_hand,
        "cached_reserved": cached_reserved,
        "ledger_reserved": ledger_reserved,
    }


def order_row(
    *,
    order_id: UUID = ORDER_ID,
    sku: str = "SKU-1042",
    qty: int = 3,
    reserved: int = 3,
) -> dict[str, object]:
    return {"id": order_id, "sku": sku, "qty": qty, "reserved": reserved}


def summary(violations: list[Violation] | tuple[Violation, ...]) -> list[tuple[object, ...]]:
    return [(v.rule, v.sku, v.expected, v.actual) for v in violations]


def test_a_clean_database_has_no_violations() -> None:
    report = check_invariants(stock_rows=[], order_rows=[])

    assert report.ok is True
    assert report.violations == ()
    assert report.errors == ()


def test_matching_stock_rows_produce_nothing() -> None:
    assert stock_violations([stock_row()]) == []


def test_matching_order_lines_produce_nothing() -> None:
    assert order_violations([order_row()]) == []


def test_i2_flags_a_cached_on_hand_that_disagrees_with_the_ledger() -> None:
    report = check_invariants(stock_rows=[stock_row(cached_on_hand=7, ledger_on_hand=9)])

    assert report.ok is False
    assert summary(report.violations) == [(InvariantRule.I2, "SKU-1042", 9, 7)]
    assert report.violations[0].note == "stock.on_hand"


def test_i3_flags_a_cached_reserved_that_disagrees_with_the_ledger() -> None:
    report = check_invariants(
        stock_rows=[stock_row(cached_reserved=2, ledger_reserved=1)],
    )

    assert summary(report.violations) == [(InvariantRule.I3, "SKU-1042", 1, 2)]
    assert report.violations[0].note == "stock.reserved"


def test_one_row_can_break_both_caches() -> None:
    report = check_invariants(
        stock_rows=[
            stock_row(cached_on_hand=7, ledger_on_hand=9, cached_reserved=2, ledger_reserved=1)
        ]
    )

    assert summary(report.violations) == [
        (InvariantRule.I2, "SKU-1042", 9, 7),
        (InvariantRule.I3, "SKU-1042", 1, 2),
    ]


def test_an_i1_only_row_is_reported_rather_than_silently_dropped() -> None:
    # §4's query also selects I1 breaches. The mapper must not return "clean"
    # for a row the query returned.
    report = check_invariants(
        stock_rows=[
            stock_row(
                cached_on_hand=3,
                ledger_on_hand=3,
                cached_reserved=5,
                ledger_reserved=5,
            )
        ],
    )

    assert summary(report.violations) == [(InvariantRule.I1, "SKU-1042", 3, 5)]
    assert report.violations[0].note == "reserved > on_hand"


def test_i5_flags_an_under_reserved_confirmed_order() -> None:
    report = check_invariants(order_rows=[order_row(qty=3, reserved=1)], stock_rows=[])

    assert summary(report.violations) == [(InvariantRule.I5, "SKU-1042", 3, 1)]
    violation = report.violations[0]
    assert violation.order_id == ORDER_ID
    assert violation.note == "confirmed order reservation"


def test_i5_flags_a_line_with_no_reservation() -> None:
    assert summary(order_violations([order_row(qty=2, reserved=0)])) == [
        (InvariantRule.I5, "SKU-1042", 2, 0)
    ]


def test_violations_are_ordered_by_rule_and_sku() -> None:
    report = check_invariants(
        stock_rows=[
            stock_row(sku="SKU-B", cached_on_hand=1, ledger_on_hand=2),
            stock_row(sku="SKU-A", cached_reserved=1, ledger_reserved=0),
            stock_row(sku="SKU-A", cached_on_hand=1, ledger_on_hand=2),
        ],
        order_rows=[order_row(sku="SKU-Z", qty=2, reserved=0)],
    )

    assert [(v.rule, v.sku) for v in report.violations] == [
        (InvariantRule.I2, "SKU-A"),
        (InvariantRule.I2, "SKU-B"),
        (InvariantRule.I3, "SKU-A"),
        (InvariantRule.I5, "SKU-Z"),
    ]


def test_malformed_stock_rows_become_errors_not_exceptions() -> None:
    report = check_invariants(
        stock_rows=[stock_row(), {"sku": "SKU-1042"}],
        order_rows=[order_row()],
    )

    assert report.ok is False
    assert report.violations == ()
    assert len(report.errors) == 1
    assert "cached_on_hand" in report.errors[0]


def test_non_mapping_rows_become_errors_not_exceptions() -> None:
    report = check_invariants(stock_rows=[None], order_rows=["not a row"])

    assert report.ok is False
    assert report.violations == ()
    assert len(report.errors) == 2


def test_a_non_iterable_input_is_an_error_not_a_crash() -> None:
    report = check_invariants(stock_rows=42)  # type: ignore[arg-type]

    assert report.ok is False
    assert len(report.errors) == 1


def test_the_stock_query_is_the_documented_i2_i3_query() -> None:
    query = " ".join(STOCK_LEDGER_QUERY.lower().split())

    assert "select s.sku" in query
    assert "left join movements m using (warehouse_id, sku)" in query
    assert "group by s.warehouse_id, s.sku, s.on_hand, s.reserved" in query
    assert "s.on_hand <> coalesce(sum(m.delta_on_hand), 0)" in query
    assert "s.reserved <> coalesce(sum(m.delta_reserved), 0)" in query


def test_the_order_query_is_the_documented_i5_query() -> None:
    query = " ".join(ORDER_RESERVATION_QUERY.lower().split())

    assert "where o.status = 'confirmed'" in query
    assert "m.reason = 'reserve'" in query
    assert "having coalesce(sum(m.delta_reserved), 0) <> l.qty" in query
