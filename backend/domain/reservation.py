"""Reservation validation for ``POST /api/orders``.

Pure domain logic: given the locked stock counts and the requested lines,
confirm every line can be reserved. The API layer owns the transaction, the
locks and the writes. See ``_docs/domain.md`` §3 (ordered ``FOR UPDATE``
reservation, all-or-nothing, per-line ``409 insufficient_stock``).
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import DomainError
from .movements import OrderLine
from .stock import StockCounts


@dataclass(frozen=True, slots=True)
class ShortLine:
    """One line that cannot be satisfied, in the shape the contract returns."""

    sku: str
    requested: int
    available: int
    short_by: int


class InsufficientStock(DomainError):
    """Every short line in one order; the whole order is rejected (US1-AC1)."""

    code = "insufficient_stock"

    def __init__(self, short: list[ShortLine]) -> None:
        self.short = list(short)
        named = ", ".join(line.sku for line in self.short)
        count = len(self.short)
        super().__init__(f"{named} {'is' if count == 1 else 'are'} short. No stock was reserved.")


def validate_availability(
    lines: list[OrderLine],
    stock_by_sku: dict[str, StockCounts],
) -> None:
    """Raise :class:`InsufficientStock` naming every short line, or return None.

    All lines are checked before any is rejected, so the response names every
    short SKU instead of stopping at the first one. A SKU with no locked stock
    row counts as unavailable (``available = 0``).
    """
    short: list[ShortLine] = []
    for line in lines:
        counts = stock_by_sku.get(line.sku)
        available = counts.available if counts is not None else 0
        if available < line.qty:
            short.append(
                ShortLine(
                    sku=line.sku,
                    requested=line.qty,
                    available=available,
                    short_by=line.qty - available,
                )
            )
    if short:
        raise InsufficientStock(short)
