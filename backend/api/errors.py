"""Problem+json exception handlers and the request-scoped trace id (issue #11).

Requests get one trace id in :func:`trace_id_middleware` — the OpenTelemetry
span's id since T6.1 (#55), stored on the request state so an error path can
reuse it even before a span is consulted. Every error path —
Starlette ``HTTPException`` (unknown route, wrong method), FastAPI
``RequestValidationError``, a malformed JSON body and the catch-all ``Exception``
— returns an ``application/problem+json`` document that reuses it.

The catch-all is deliberately opaque: the response carries a fixed detail, and
the log records only the exception class and the trace id. A DSN, SQL snippet,
stack trace or customer detail never leaves the process through this path.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.api.problems import (
    current_trace_id,
    problem,
    reset_trace_id,
    set_trace_id,
    validation_error,
)

logger = logging.getLogger(__name__)

# Field names whose values are never echoed back, even in a validation error.
_SECRET_FIELD_HINTS = (
    "address",
    "api_key",
    "apikey",
    "authorization",
    "card",
    "credential",
    "email",
    "password",
    "passwd",
    "phone",
    "private_key",
    "secret",
    "ssn",
    "token",
)

_MAX_VALUE_LENGTH = 200

# HTTP status -> (type, title, detail). Only the statuses the framework itself
# raises are named; anything else falls back to a generic category below.
_HTTP_PROBLEMS: dict[int, tuple[str, str, str]] = {
    404: ("not_found", "Not found", "The requested resource does not exist."),
    405: (
        "method_not_allowed",
        "Method not allowed",
        "The HTTP method is not allowed for this path.",
    ),
    422: ("validation_error", "Invalid request", "The request failed validation."),
    503: ("service_unavailable", "Service unavailable", "The service is not available."),
}


async def trace_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Give every request one trace id and clear it when the request ends.

    ``current_trace_id`` returns the active OpenTelemetry span's id, so the
    problem document, the JSON log records and the metric exemplar of one
    request cannot disagree (AC2). Outside a span it mints one, which keeps the
    handlers usable in a probe app that is not instrumented.
    """
    trace_id = current_trace_id()
    token = set_trace_id(trace_id)
    request.state.trace_id = trace_id
    try:
        return await call_next(request)
    except Exception as exc:
        # Catch here as well as in the registered handler: Starlette's
        # ServerErrorMiddleware re-raises after answering, which lets uvicorn
        # print the traceback. The middleware contains the failure so the only
        # error log is the safe one below.
        return await unhandled_exception_handler(request, exc)
    finally:
        reset_trace_id(token)


def _problem_for_status(status_code: int) -> tuple[str, str, str]:
    known = _HTTP_PROBLEMS.get(status_code)
    if known is not None:
        return known
    if status_code >= 500:
        return ("unexpected", "Unexpected error", "An unexpected error occurred.")
    return ("http_error", "Request failed", "The request could not be completed.")


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Map a framework ``HTTPException`` (including 404 and 405) to problem+json."""
    type_, title, detail = _problem_for_status(exc.status_code)
    return problem(
        status_code=exc.status_code,
        type_=type_,
        title=title,
        detail=detail,
        headers=exc.headers,
    )


def _field_path(location: tuple[Any, ...]) -> str:
    """A dot-separated field path without FastAPI's ``body``/``query`` prefix."""
    parts = [
        str(part) for part in location if part not in {"body", "query", "path", "header", "cookie"}
    ]
    return ".".join(parts) or "body"


def _is_secret(location: tuple[Any, ...]) -> bool:
    return any(hint in str(part).lower() for part in location for hint in _SECRET_FIELD_HINTS)


def _safe_value(value: Any) -> tuple[bool, Any]:
    """Return ``(include, value)``; structured and null input is never echoed."""
    if isinstance(value, str):
        if len(value) > _MAX_VALUE_LENGTH:
            return True, value[:_MAX_VALUE_LENGTH] + "..."
        return True, value
    if isinstance(value, (bool, int, float)):
        return True, value
    return False, None


def _validation_entries(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Field path, validator message and — when safe — the offending scalar."""
    entries: list[dict[str, Any]] = []
    for error in exc.errors():
        location = tuple(error.get("loc", ()))
        entry: dict[str, Any] = {"field": _field_path(location)}
        message = error.get("msg")
        if isinstance(message, str) and message:
            entry["message"] = message
        if not _is_secret(location) and "input" in error:
            include, value = _safe_value(error["input"])
            if include:
                entry["value"] = value
        entries.append(entry)
    return entries


async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """A framework validation failure is a 422 problem with field-level detail.

    ``RequestValidationError.errors()`` carries an ``input`` (and sometimes the
    whole body) that can contain a password or token. Only scalar values from
    non-secret fields are echoed; structured input is dropped entirely.
    """
    errors = exc.errors()
    # Pydantic body models parse JSON before the handler runs, so a malformed
    # body arrives here as a ``json_invalid`` entry rather than a
    # ``JSONDecodeError``. Keep the specific message the API has always used.
    if any(error.get("type") == "json_invalid" for error in errors):
        detail = "Request body is not valid JSON."
    else:
        detail = "The request failed validation."
    return problem(
        status_code=422,
        type_="validation_error",
        title="Invalid request",
        detail=detail,
        errors=_validation_entries(exc),
    )


async def malformed_json_handler(
    request: Request,
    exc: json.JSONDecodeError | UnicodeDecodeError,
) -> JSONResponse:
    """A body that is not JSON is a client error, not a 500 (pre-existing gap)."""
    return validation_error(
        "Request body is not valid JSON.",
        errors=[{"field": "body", "message": "Request body is not valid JSON."}],
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Every unhandled failure is opaque problem+json with the request trace id."""
    trace_id = getattr(getattr(request, "state", None), "trace_id", None) or current_trace_id()
    logger.error("Unhandled %s (trace_id=%s)", type(exc).__name__, trace_id)
    return problem(
        status_code=500,
        type_="unexpected",
        title="Unexpected error",
        detail="An unexpected error occurred.",
        trace_id=trace_id,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install the middleware and handlers on an application."""
    app.add_middleware(BaseHTTPMiddleware, dispatch=trace_id_middleware)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(json.JSONDecodeError, malformed_json_handler)
    app.add_exception_handler(UnicodeDecodeError, malformed_json_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
