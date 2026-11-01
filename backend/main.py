"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.api.health import router as health_router
from backend.api.orders import router as orders_router
from backend.api.problems import problem
from backend.config import get_settings


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.include_router(health_router)
    app.include_router(orders_router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Every unhandled failure is still ``application/problem+json`` with a trace id."""
        return problem(
            status_code=500,
            type_="unexpected",
            title="Unexpected error",
            detail="An unexpected error occurred.",
        )

    return app


app = create_app()
