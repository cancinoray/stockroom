"""RFC 9457 ``application/problem+json`` responses carrying a ``trace_id``.

Every error this API returns is a problem document so a user-visible error can
be traced through the logs and traces. The helper is intentionally small so
every endpoint builds errors in one shape.

The trace id is request-scoped: :func:`current_trace_id` reads a ``ContextVar``
that the HTTP middleware in :mod:`backend.api.errors` sets once per request and
clears in ``finally``. Error handlers and endpoint helpers therefore share one
id for a request instead of minting a fresh one per call. The fallback keeps the
helper usable outside a request (for example in a unit test), where a new id is
the only sensible answer.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

_current_trace_id: ContextVar[str | None] = ContextVar("stockroom_trace_id", default=None)


def new_trace_id() -> str:
    """A fresh correlation id, in the UUIDv4 hex form used by the contract examples."""
    return uuid.uuid4().hex


def set_trace_id(trace_id: str) -> Token[str | None]:
    """Bind ``trace_id`` to the current request context."""
    return _current_trace_id.set(trace_id)


def reset_trace_id(token: Token[str | None]) -> None:
    """Restore the previous context, so a later request cannot inherit this id."""
    _current_trace_id.reset(token)


def current_trace_id() -> str:
    """The id of the request being handled, or a new one outside a request."""
    trace_id = _current_trace_id.get()
    if trace_id is None:
        trace_id = new_trace_id()
        _current_trace_id.set(trace_id)
    return trace_id


def problem(
    *,
    status_code: int,
    type_: str,
    title: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
    trace_id: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build a problem document using the request's trace id."""
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status_code,
        "detail": detail,
        "trace_id": trace_id or current_trace_id(),
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content=body,
        headers=dict(headers) if headers is not None else None,
    )


def validation_error(
    detail: str,
    *,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """A ``422 validation_error`` problem document, optionally with field detail."""
    return problem(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        type_="validation_error",
        title="Invalid request",
        detail=detail,
        errors=errors,
    )
