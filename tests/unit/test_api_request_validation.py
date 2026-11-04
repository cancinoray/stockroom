"""Request-body validation seams: US1-AC4 and US5-AC4.

Two pure places enforce the wire rules: the strict Pydantic models in
``backend.api.schemas`` and the note normaliser in ``backend.api.stock``. Both
run without a database or an HTTP server, which is why product-spec.md §6 tags
these claims ``unit``. Behaviour is defined in product-spec.md §6; the ledger
rules it protects are in _docs/domain.md §2.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.api.schemas import AdjustRequest, CreateOrderLine
from backend.api.stock import _validated_note


def problem(response: Any) -> dict[str, Any]:
    """Assert ``response`` is a 422 problem document and return its body."""
    assert isinstance(response, JSONResponse)
    assert response.status_code == 422
    assert response.media_type == "application/problem+json"

    body = json.loads(response.body)
    assert body["type"] == "validation_error"
    assert body["trace_id"]
    return body


@pytest.mark.parametrize("qty", [0, -1, 1.5, "3", None, True])
def test_create_order_line_rejects_a_value_that_is_not_a_positive_integer(
    qty: object,
) -> None:
    # US1-AC4 at the wire boundary: the same values OrderLine refuses
    # (test_domain_ledger.py) are 422s before any stock is read. ``True`` is an
    # ``int`` subclass, so strict mode has to exclude bool too.
    with pytest.raises(ValidationError):
        CreateOrderLine(sku="SKU-1042", qty=qty)  # type: ignore[arg-type]


def test_create_order_line_accepts_a_positive_integer() -> None:
    assert CreateOrderLine(sku="SKU-1042", qty=1).qty == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"sku": "SKU-1042", "delta": -1},  # US5-AC4: note is required
        {"sku": "SKU-1042", "delta": -1, "note": ""},  # and must not be empty
    ],
)
def test_adjust_request_rejects_a_missing_or_empty_note(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AdjustRequest(**payload)


def test_adjust_request_alone_does_not_trim_a_blank_note() -> None:
    # The model enforces presence and a non-empty string; only _validated_note
    # trims. Pinning the split keeps the whitespace rule where it is tested.
    assert AdjustRequest(sku="SKU-1042", delta=-1, note="   ").note == "   "


def test_an_adjustment_note_is_required() -> None:
    assert "Note is required" in problem(_validated_note({}, required=True))["detail"]


@pytest.mark.parametrize("note", ["", "   ", " \n\t "])
def test_a_blank_adjustment_note_is_rejected(note: str) -> None:
    # US5-AC4: white space is not an explanation for a count difference.
    assert "Note is required" in problem(_validated_note({"note": note}, required=True))["detail"]


def test_a_non_text_note_is_rejected() -> None:
    assert "Note must be text" in problem(_validated_note({"note": 5}, required=True))["detail"]


def test_a_valid_note_is_trimmed_and_returned() -> None:
    assert _validated_note({"note": "  cycle count  "}, required=True) == "cycle count"


def test_an_optional_note_may_be_absent() -> None:
    # Receiving does not demand a note; absent is different from blank.
    assert _validated_note({}, required=False) is None


def test_a_blank_note_is_rejected_even_when_it_is_optional() -> None:
    assert "Note is required" in problem(_validated_note({"note": "  "}, required=False))["detail"]
