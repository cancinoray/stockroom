"""RFC 9457 ``application/problem+json`` responses carrying a ``trace_id``.

Every error this API returns is a problem document so a user-visible error can
be traced through the logs and traces. The helper is intentionally small so
every endpoint builds errors in one shape.

The trace id is the request's OpenTelemetry trace id (T6.1 / #55):
:func:`current_trace_id` returns the active span's 32-hex id, so the body, the
trace and every log line for the request carry the same value. The HTTP
middleware in :mod:`backend.api.errors` also stores it in a ``ContextVar`` for
the paths where no span exists, and :func:`current_trace_id` falls back to a
minted id outside a request (a unit test calling ``problem`` directly). There
is never a second id inside a traced request.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from backend import telemetry

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
    """The request's trace id: the active span's, else a bound or minted one.

    Inside a traced request the span wins, so the id in the problem document is
    the id in the trace and in the logs (AC2).
    """
    span_trace_id = telemetry.current_trace_id()
    if span_trace_id is not None:
        return span_trace_id
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
    # AC1: the type reaches the span as an attribute; a rejected order is an
    # error span, never a recorded stack trace.
    telemetry.note_problem(status_code, type_)
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
