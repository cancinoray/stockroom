"""Pure movement writer: order lines in, ledger rows out.

The ledger table in ``_docs/domain.md`` §2 is the specification:

===========  ===============  ================
reason       delta_on_hand    delta_reserved
===========  ===============  ================
reserve      0                +qty
release      0                -qty
ship         -qty             -qty
===========  ===============  ================

Rows are returned as values, never inserted. The caller (#8) owns the
transaction, the locks and the counter update.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from .errors import InvalidQuantity


class MovementReason(StrEnum):
    """The ``movements.reason`` check constraint, in one place."""

    RECEIVE = "receive"
    ADJUST = "adjust"
    RESERVE = "reserve"
    RELEASE = "release"
    SHIP = "ship"


@dataclass(frozen=True, slots=True)
class Movement:
    """One append-only ledger row, ready to insert."""

    warehouse_id: UUID
    sku: str
    delta_on_hand: int
    delta_reserved: int
    reason: MovementReason
    actor: str
    order_id: UUID | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class OrderLine:
    """The order-line fields the writer needs; ``qty`` mirrors ``qty > 0``."""

    order_id: UUID
    sku: str
    qty: int

    def __post_init__(self) -> None:
        if not isinstance(self.qty, int) or isinstance(self.qty, bool) or self.qty <= 0:
            raise InvalidQuantity(self.qty)


def _movements(
    lines: Iterable[OrderLine],
    *,
    reason: MovementReason,
    warehouse_id: UUID,
    actor: str,
) -> tuple[Movement, ...]:
    movements: list[Movement] = []
    # Ascending SKU keeps the write order identical to the lock order in §3.
    for line in sorted(lines, key=lambda item: item.sku):
        if reason is MovementReason.RESERVE:
            delta_on_hand, delta_reserved = 0, line.qty
        elif reason is MovementReason.RELEASE:
            delta_on_hand, delta_reserved = 0, -line.qty
        elif reason is MovementReason.SHIP:
            delta_on_hand, delta_reserved = -line.qty, -line.qty
        else:  # pragma: no cover - guarded by the three public factories
            raise ValueError(f"{reason!r} is not an order movement reason")
        movements.append(
            Movement(
                warehouse_id=warehouse_id,
                sku=line.sku,
                delta_on_hand=delta_on_hand,
                delta_reserved=delta_reserved,
                reason=reason,
                actor=actor,
                order_id=line.order_id,
                note=None,
            )
        )
    return tuple(movements)


def reserve_movements(
    lines: Iterable[OrderLine],
    *,
    warehouse_id: UUID,
    actor: str,
) -> tuple[Movement, ...]:
    """Rows for ``POST /api/orders``: reserve ``qty`` per line."""
    return _movements(
        lines,
        reason=MovementReason.RESERVE,
        warehouse_id=warehouse_id,
        actor=actor,
    )


def release_movements(
    lines: Iterable[OrderLine],
    *,
    warehouse_id: UUID,
    actor: str,
) -> tuple[Movement, ...]:
    """Rows for cancelling a confirmed order: give the reservation back."""
    return _movements(
        lines,
        reason=MovementReason.RELEASE,
        warehouse_id=warehouse_id,
        actor=actor,
    )


def ship_movements(
    lines: Iterable[OrderLine],
    *,
    warehouse_id: UUID,
    actor: str,
) -> tuple[Movement, ...]:
    """Rows for fulfilling a confirmed order: stock and reservation both go."""
    return _movements(
        lines,
        reason=MovementReason.SHIP,
        warehouse_id=warehouse_id,
        actor=actor,
    )
