"""Order lifecycle state machine.

``product-spec.md`` §5 defines exactly two moves: ``confirmed -> cancelled`` and
``confirmed -> fulfilled``. Nothing else is legal, including a repeated
transition or any move out of a terminal state. The predicate is the primary
API so callers can validate without exceptions; ``transition`` is the
exception-raising convenience on top of it.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import InvalidTransition


class OrderStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FULFILLED = "fulfilled"


ALLOWED_TRANSITIONS: frozenset[tuple[OrderStatus, OrderStatus]] = frozenset(
    {
        (OrderStatus.CONFIRMED, OrderStatus.CANCELLED),
        (OrderStatus.CONFIRMED, OrderStatus.FULFILLED),
    }
)


def _coerce(value: object) -> OrderStatus | None:
    """Return the matching status, or ``None`` when ``value`` is not one."""
    if isinstance(value, OrderStatus):
        return value
    try:
        return OrderStatus(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _label(value: object) -> str:
    return value.value if isinstance(value, OrderStatus) else str(value)


def can_transition(current: object, target: object) -> bool:
    """Return whether ``current -> target`` is one of the two legal moves.

    Unknown status names and repeated transitions are ``False`` rather than an
    exception, so a caller can render a decision without a ``try``.
    """
    source = _coerce(current)
    destination = _coerce(target)
    return (
        source is not None
        and destination is not None
        and (source, destination) in ALLOWED_TRANSITIONS
    )


def transition(current: object, target: object) -> OrderStatus:
    """Return the target status, or raise :class:`InvalidTransition`.

    Accepts statuses as either :class:`OrderStatus` or their string values so
    the API layer can pass a persisted ``orders.status`` straight through.
    """
    source = _coerce(current)
    destination = _coerce(target)
    if source is None or destination is None or (source, destination) not in ALLOWED_TRANSITIONS:
        raise InvalidTransition(_label(current), _label(target))
    return destination
