"""Order lifecycle rules: product-spec §5, US3-AC2, US3-AC3, US4-AC3.

The state machine is the only place a transition is judged. It returns the new
status or raises a domain error; mapping that error to ``409 invalid_transition``
is the API layer's job.
"""

import pytest

from backend.domain import (
    InvalidTransition,
    OrderStatus,
    can_transition,
    transition,
)

ALLOWED = {
    (OrderStatus.CONFIRMED, OrderStatus.CANCELLED),
    (OrderStatus.CONFIRMED, OrderStatus.FULFILLED),
}
ALL_PAIRS = [(current, target) for current in OrderStatus for target in OrderStatus]


@pytest.mark.parametrize(("current", "target"), ALL_PAIRS)
def test_only_confirmed_may_leave_its_state(current: OrderStatus, target: OrderStatus) -> None:
    if (current, target) in ALLOWED:
        assert can_transition(current, target) is True
        assert transition(current, target) is target
    else:
        assert can_transition(current, target) is False
        with pytest.raises(InvalidTransition):
            transition(current, target)


def test_cancelling_an_already_cancelled_order_is_rejected() -> None:
    # US3-AC2: a repeated cancel must not write a second release.
    with pytest.raises(InvalidTransition) as raised:
        transition(OrderStatus.CANCELLED, OrderStatus.CANCELLED)

    assert raised.value.code == "invalid_transition"
    assert raised.value.current == "cancelled"
    assert raised.value.target == "cancelled"


def test_a_fulfilled_order_cannot_be_cancelled() -> None:
    # US3-AC3.
    assert can_transition(OrderStatus.FULFILLED, OrderStatus.CANCELLED) is False
    with pytest.raises(InvalidTransition):
        transition(OrderStatus.FULFILLED, OrderStatus.CANCELLED)


def test_a_cancelled_order_cannot_be_fulfilled() -> None:
    # US4-AC3.
    assert can_transition(OrderStatus.CANCELLED, OrderStatus.FULFILLED) is False
    with pytest.raises(InvalidTransition):
        transition(OrderStatus.CANCELLED, OrderStatus.FULFILLED)


def test_a_confirmed_order_cannot_transition_to_itself() -> None:
    with pytest.raises(InvalidTransition):
        transition(OrderStatus.CONFIRMED, OrderStatus.CONFIRMED)


def test_status_strings_are_accepted() -> None:
    assert transition("confirmed", "fulfilled") is OrderStatus.FULFILLED


def test_an_unknown_status_is_an_invalid_transition() -> None:
    assert can_transition("pending", OrderStatus.CONFIRMED) is False
    with pytest.raises(InvalidTransition) as raised:
        transition("pending", OrderStatus.CONFIRMED)

    assert raised.value.current == "pending"


def test_the_rejection_names_both_statuses() -> None:
    with pytest.raises(InvalidTransition) as raised:
        transition(OrderStatus.FULFILLED, OrderStatus.CANCELLED)

    message = str(raised.value)
    assert "fulfilled" in message
    assert "cancelled" in message
