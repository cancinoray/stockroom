"""Liveness and build metadata endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.config import get_settings
from backend.db.session import DatabaseStatus, probe_database

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    db: str


class ServiceUnavailableProblem(BaseModel):
    """The contract's ``ServiceUnavailableProblem`` body."""

    type: str
    title: str
    status: int
    detail: str
    trace_id: str


class VersionResponse(BaseModel):
    version: str
    commit: str
    build_time: str
    environment: str


@router.get(
    "/healthz",
    response_model=HealthResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "The configured database is unreachable",
            "content": {
                "application/problem+json": {
                    "schema": ServiceUnavailableProblem.model_json_schema()
                }
            },
        }
    },
)
def healthz(
    db_status: Annotated[DatabaseStatus, Depends(probe_database)],
) -> HealthResponse | JSONResponse:
    """Report liveness and whether the database answers a query.

    ``db`` is ``not_configured`` when no DSN is set (the walking-skeleton
    response from #1) and ``ok`` when ``SELECT 1`` succeeds.

    A failed connection is a ``503`` with an ``application/problem+json`` body
    matching the contract's ``ServiceUnavailableProblem``. ``trace_id`` is a
    per-request placeholder until tracing is centralized in #11.
    """
    if db_status == "unreachable":
        problem = ServiceUnavailableProblem(
            type="service_unavailable",
            title="Service unavailable",
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The database is not reachable.",
            trace_id=uuid.uuid4().hex,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/problem+json",
            content=problem.model_dump(),
        )
    return HealthResponse(status="ok", db=db_status)


@router.get("/api/version")
def version() -> VersionResponse:
    """Report the deployed version, commit and build time."""
    settings = get_settings()
    return VersionResponse(
        version=settings.app_version,
        commit=settings.commit,
        build_time=settings.build_time,
        environment=settings.environment,
    )
