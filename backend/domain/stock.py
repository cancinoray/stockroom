"""Availability and the low-stock rule.

``available = on_hand - reserved`` is the number an operator acts on, so it is
computed in one place (US4-AC2, US6-AC1). Fulfilment writes ``-qty`` to both
counters, which is why availability is unchanged by a ship movement.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .movements import Movement


@dataclass(frozen=True, slots=True)
class StockCounts:
    """The two cached counters for one ``(warehouse, sku)``."""

    on_hand: int
    reserved: int

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved

    def is_low(self, reorder_point: int) -> bool:
        """Low stock is ``available <= reorder_point`` (US6-AC1 boundary)."""
        return self.available <= reorder_point

    def apply(self, movement: Movement) -> StockCounts:
        """Project one movement onto the counters without touching a database."""
        return StockCounts(
            on_hand=self.on_hand + movement.delta_on_hand,
            reserved=self.reserved + movement.delta_reserved,
        )

    def apply_all(self, movements: Iterable[Movement]) -> StockCounts:
        counts = self
        for movement in movements:
            counts = counts.apply(movement)
        return counts
