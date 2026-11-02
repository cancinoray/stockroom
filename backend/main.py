"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from backend.api.errors import register_error_handlers
from backend.api.health import router as health_router
from backend.api.orders import router as orders_router
from backend.api.products import router as products_router
from backend.api.stock import router as stock_router
from backend.config import get_settings


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.include_router(health_router)
    app.include_router(orders_router)
    app.include_router(products_router)
    app.include_router(stock_router)
    register_error_handlers(app)
    return app


app = create_app()
