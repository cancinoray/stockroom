"""Pure domain layer: order lifecycle, ledger rows, invariants.

Everything here is importable without a database session or an HTTP client.
The API layer maps these results and errors to responses; the persistence layer
owns transactions. See ``AGENTS.md`` rules 1–3 and ``_docs/domain.md``.
"""

from __future__ import annotations

from .errors import DomainError, InvalidQuantity, InvalidTransition
from .invariants import (
    ORDER_RESERVATION_QUERY,
    STOCK_LEDGER_QUERY,
    InvariantReport,
    InvariantRule,
    Violation,
    check_invariants,
    order_violations,
    stock_violations,
)
from .movements import (
    Movement,
    MovementReason,
    OrderLine,
    release_movements,
    reserve_movements,
    ship_movements,
)
from .orders import (
    ALLOWED_TRANSITIONS,
    OrderStatus,
    can_transition,
    transition,
)
from .stock import StockCounts

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ORDER_RESERVATION_QUERY",
    "STOCK_LEDGER_QUERY",
    "DomainError",
    "InvalidQuantity",
    "InvalidTransition",
    "InvariantReport",
    "InvariantRule",
    "Movement",
    "MovementReason",
    "OrderLine",
    "OrderStatus",
    "StockCounts",
    "Violation",
    "can_transition",
    "check_invariants",
    "order_violations",
    "release_movements",
    "reserve_movements",
    "ship_movements",
    "stock_violations",
    "transition",
]
