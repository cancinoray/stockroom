"""Domain errors.

These are the only errors the pure layer raises. Mapping them to HTTP responses
(``409 invalid_transition`` and friends) is the API layer's job.
"""

from __future__ import annotations


class DomainError(ValueError):
    """Base class for a rule violation raised by the domain layer."""

    code = "domain_error"


class InvalidQuantity(DomainError):
    """An order line asked for a zero or negative quantity (``qty > 0``)."""

    code = "invalid_quantity"

    def __init__(self, qty: object) -> None:
        self.qty = qty
        super().__init__(f"quantity must be a positive integer, got {qty!r}")


class InvalidTransition(DomainError):
    """An order lifecycle move that product-spec §5 does not allow."""

    code = "invalid_transition"

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"cannot transition from {current!r} to {target!r}")
