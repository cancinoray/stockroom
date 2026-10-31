"""Invariant queries and row mapping (``_docs/domain.md`` §4).

The SQL lives here next to the mapping so the query and the rule cannot drift.
``check_invariants`` is deliberately total: a caller can hand it whatever a
cursor returned, and malformed rows become entries in ``errors`` rather than an
exception. A check that crashes is worse than no check.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

STOCK_LEDGER_QUERY = """
SELECT s.sku,
       s.on_hand            AS cached_on_hand,
       COALESCE(SUM(m.delta_on_hand), 0)  AS ledger_on_hand,
       s.reserved           AS cached_reserved,
       COALESCE(SUM(m.delta_reserved), 0) AS ledger_reserved
  FROM stock s
  LEFT JOIN movements m USING (warehouse_id, sku)
 GROUP BY s.warehouse_id, s.sku, s.on_hand, s.reserved
HAVING s.on_hand  <> COALESCE(SUM(m.delta_on_hand), 0)
    OR s.reserved <> COALESCE(SUM(m.delta_reserved), 0)
    OR s.reserved > s.on_hand
    OR s.on_hand < 0
    OR s.reserved < 0
"""

ORDER_RESERVATION_QUERY = """
SELECT o.id, l.sku, l.qty, COALESCE(SUM(m.delta_reserved), 0) AS reserved
  FROM orders o
  JOIN order_lines l ON l.order_id = o.id
  LEFT JOIN movements m
         ON m.order_id = o.id AND m.sku = l.sku AND m.reason = 'reserve'
 WHERE o.status = 'confirmed'
 GROUP BY o.id, l.sku, l.qty
HAVING COALESCE(SUM(m.delta_reserved), 0) <> l.qty
"""


class InvariantRule(StrEnum):
    """Rule ids used by the endpoint and the alert payload."""

    I1 = "I1"
    I2 = "I2"
    I3 = "I3"
    I5 = "I5"


_RULE_RANK = {
    InvariantRule.I1: 0,
    InvariantRule.I2: 1,
    InvariantRule.I3: 2,
    InvariantRule.I5: 3,
}


@dataclass(frozen=True, slots=True)
class Violation:
    """One disagreeing pair: what the ledger says and what the cache says."""

    rule: InvariantRule
    sku: str
    expected: int
    actual: int
    note: str
    order_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class InvariantReport:
    """The complete answer to ``GET /api/invariants`` before serialisation."""

    violations: tuple[Violation, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations and not self.errors


class _RowError(ValueError):
    """A row that cannot be mapped; reported, never raised to the caller."""


def _require_mapping(row: object) -> Mapping[str, object]:
    if not isinstance(row, Mapping):
        raise _RowError(f"expected a mapping, got {type(row).__name__}")
    return row


def _field(row: Mapping[str, object], name: str) -> object:
    if name not in row:
        raise _RowError(f"missing {name}")
    return row[name]


def _int_field(row: Mapping[str, object], name: str) -> int:
    value = _field(row, name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _RowError(f"{name} must be an integer, got {type(value).__name__}")
    return value


def _str_field(row: Mapping[str, object], name: str) -> str:
    value = _field(row, name)
    if not isinstance(value, str):
        raise _RowError(f"{name} must be a string, got {type(value).__name__}")
    return value


def _uuid_field(row: Mapping[str, object], name: str) -> UUID:
    value = _field(row, name)
    if not isinstance(value, UUID):
        raise _RowError(f"{name} must be a UUID, got {type(value).__name__}")
    return value


def _stock_row_violations(row: object) -> list[Violation]:
    mapped = _require_mapping(row)
    sku = _str_field(mapped, "sku")
    cached_on_hand = _int_field(mapped, "cached_on_hand")
    ledger_on_hand = _int_field(mapped, "ledger_on_hand")
    cached_reserved = _int_field(mapped, "cached_reserved")
    ledger_reserved = _int_field(mapped, "ledger_reserved")

    violations: list[Violation] = []
    if cached_on_hand != ledger_on_hand:
        violations.append(
            Violation(
                rule=InvariantRule.I2,
                sku=sku,
                expected=ledger_on_hand,
                actual=cached_on_hand,
                note="stock.on_hand",
            )
        )
    if cached_reserved != ledger_reserved:
        violations.append(
            Violation(
                rule=InvariantRule.I3,
                sku=sku,
                expected=ledger_reserved,
                actual=cached_reserved,
                note="stock.reserved",
            )
        )
    # The query also selects the I1 breaches. When a cache already disagrees
    # with the ledger, I2/I3 is the actionable finding and I1 would only repeat
    # it; an "I1-only" row is one whose sums match but whose counters are still
    # illegal. Either way a returned row is never silently clean.
    if cached_on_hand == ledger_on_hand and cached_reserved == ledger_reserved:
        if cached_reserved > cached_on_hand:
            violations.append(
                Violation(
                    rule=InvariantRule.I1,
                    sku=sku,
                    expected=cached_on_hand,
                    actual=cached_reserved,
                    note="reserved > on_hand",
                )
            )
        if cached_on_hand < 0:
            violations.append(
                Violation(
                    rule=InvariantRule.I1,
                    sku=sku,
                    expected=0,
                    actual=cached_on_hand,
                    note="on_hand < 0",
                )
            )
        if cached_reserved < 0:
            violations.append(
                Violation(
                    rule=InvariantRule.I1,
                    sku=sku,
                    expected=0,
                    actual=cached_reserved,
                    note="reserved < 0",
                )
            )
    return violations


def _order_row_violations(row: object) -> list[Violation]:
    mapped = _require_mapping(row)
    order_id = _uuid_field(mapped, "id")
    sku = _str_field(mapped, "sku")
    qty = _int_field(mapped, "qty")
    reserved = _int_field(mapped, "reserved")

    if reserved == qty:
        return []
    return [
        Violation(
            rule=InvariantRule.I5,
            sku=sku,
            expected=qty,
            actual=reserved,
            note="confirmed order reservation",
            order_id=order_id,
        )
    ]


def _sorted(violations: list[Violation]) -> list[Violation]:
    return sorted(
        violations,
        key=lambda violation: (
            _RULE_RANK[violation.rule],
            violation.sku,
            str(violation.order_id or ""),
        ),
    )


def _iterate(rows: object) -> Iterator[object]:
    try:
        iterator = iter(rows)  # type: ignore[arg-type]
    except TypeError:
        return
    yield from iterator


def stock_violations(rows: object) -> list[Violation]:
    """Map stock query rows to I1/I2/I3 violations, skipping bad rows."""
    violations: list[Violation] = []
    for row in _iterate(rows):
        try:
            violations.extend(_stock_row_violations(row))
        except _RowError:
            continue
    return _sorted(violations)


def order_violations(rows: object) -> list[Violation]:
    """Map order query rows to I5 violations, skipping bad rows."""
    violations: list[Violation] = []
    for row in _iterate(rows):
        try:
            violations.extend(_order_row_violations(row))
        except _RowError:
            continue
    return _sorted(violations)


def check_invariants(
    stock_rows: object = None,
    order_rows: object = None,
) -> InvariantReport:
    """Build a report from rows a caller fetched with the two queries above."""
    violations: list[Violation] = []
    errors: list[str] = []

    sources: tuple[tuple[str, object, object], ...] = (
        ("stock", stock_rows, _stock_row_violations),
        ("order", order_rows, _order_row_violations),
    )
    for label, rows, mapper in sources:
        if rows is None:
            continue
        try:
            iterator = iter(rows)  # type: ignore[arg-type]
        except TypeError:
            errors.append(f"{label}_rows is not iterable: {type(rows).__name__}")
            continue
        for index, row in enumerate(iterator):
            try:
                violations.extend(mapper(row))  # type: ignore[operator]
            except _RowError as exc:
                errors.append(f"{label} row {index}: {exc}")

    return InvariantReport(
        violations=tuple(_sorted(violations)),
        errors=tuple(errors),
    )
