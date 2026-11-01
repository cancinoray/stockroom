"""RFC 9457 ``application/problem+json`` responses carrying a ``trace_id``.

Every error this API returns is a problem document so a user-visible error can
be traced through the logs and traces. The helper is intentionally small so
every endpoint builds errors in one shape.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse


def problem(
    *,
    status_code: int,
    type_: str,
    title: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """Build a problem document with a fresh per-request trace id."""
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status_code,
        "detail": detail,
        "trace_id": uuid.uuid4().hex,
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content=body,
    )


def validation_error(detail: str) -> JSONResponse:
    """A ``422 validation_error`` problem document."""
    return problem(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        type_="validation_error",
        title="Invalid request",
        detail=detail,
    )
