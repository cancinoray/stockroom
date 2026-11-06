"""Liveness and build metadata endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.openapi import SERVICE_UNAVAILABLE, UNEXPECTED_ERROR
from backend.api.problems import current_trace_id
from backend.api.schemas import Health, Version
from backend.config import get_settings
from backend.db.session import DatabaseStatus, probe_database

router = APIRouter()


class ServiceUnavailableProblem(BaseModel):
    """The contract's ``ServiceUnavailableProblem`` body."""

    type: str
    title: str
    status: int
    detail: str
    trace_id: str


@router.get(
    "/healthz",
    response_model=Health,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: SERVICE_UNAVAILABLE,
        "default": UNEXPECTED_ERROR,
    },
)
def healthz(
    db_status: Annotated[DatabaseStatus, Depends(probe_database)],
) -> Health | JSONResponse:
    """Report liveness and whether the database answers a query.

    ``db`` is ``not_configured`` when no DSN is set (the walking-skeleton
    response from #1) and ``ok`` when ``SELECT 1`` succeeds.

    A failed connection is a ``503`` with an ``application/problem+json`` body
    matching the contract's ``ServiceUnavailableProblem``. ``trace_id`` is the
    request's shared id (T6.1 / #55), never a second one minted here.
    """
    if db_status == "unreachable":
        problem = ServiceUnavailableProblem(
            type="service_unavailable",
            title="Service unavailable",
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The database is not reachable.",
            trace_id=current_trace_id(),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/problem+json",
            content=problem.model_dump(),
        )
    return Health(status="ok", db=db_status)


@router.get(
    "/api/version",
    response_model=Version,
    responses={"default": UNEXPECTED_ERROR},
)
def version() -> Version:
    """Report the deployed version, commit and build time."""
    settings = get_settings()
    return Version(
        version=settings.app_version,
        commit=settings.commit,
        build_time=settings.build_time,
        environment=settings.environment,
    )
