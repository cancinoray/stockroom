"""Liveness and build metadata endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    db: str


class VersionResponse(BaseModel):
    version: str
    commit: str
    build_time: str
    environment: str


@router.get("/healthz")
def healthz() -> HealthResponse:
    """Report that the process is serving requests.

    The database probe is wired in with the schema task; until then the field is
    explicit rather than pretending a database was checked.
    """
    return HealthResponse(status="ok", db="not_configured")


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
