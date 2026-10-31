"""Liveness and build metadata endpoints."""

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
            "model": HealthResponse,
            "description": "The configured database is unreachable",
        }
    },
)
def healthz(
    db_status: Annotated[DatabaseStatus, Depends(probe_database)],
) -> HealthResponse | JSONResponse:
    """Report liveness and whether the database answers a query.

    ``db`` is ``not_configured`` when no DSN is set (the walking-skeleton
    response from #1), ``ok`` when ``SELECT 1`` succeeds, and ``unreachable``
    with a ``503`` when the connection fails.
    """
    if db_status == "unreachable":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "db": db_status},
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
