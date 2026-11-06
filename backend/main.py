"""FastAPI application factory.

Observability is installed here and nowhere else: :mod:`backend.telemetry`
owns the providers, the JSON logging and the request middleware, and the
lifespan starts its background drift check (T6.1 / #55).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import telemetry
from backend.api.errors import register_error_handlers
from backend.api.health import router as health_router
from backend.api.openapi import build_openapi
from backend.api.orders import router as orders_router
from backend.api.products import router as products_router
from backend.api.stock import router as stock_router
from backend.config import get_settings

# The first path segment of anything that is not a client route. These keep
# their existing handlers (or their existing problem+json 404); the SPA
# fallback never answers for them (issue #46, AC6).
_NON_SPA_SEGMENTS = frozenset({"api", "healthz"})


def _mount_frontend(app: FastAPI, directory: Path) -> None:
    """Serve a Vite build from ``directory``, with a client-route fallback.

    Registered after the API routers, so the API is matched first. With no
    build on disk — ``make run`` on a fresh clone — nothing is registered and
    the app behaves exactly as it did before T5.1.

    A request resolves to a built file only when it stays inside the build
    directory. Anything else falls back to ``index.html``, except paths under
    ``/assets``, dotfiles and traversal attempts, which stay ``404`` so a
    missing asset is never hidden behind the app shell.
    """
    index = directory / "index.html"
    if not index.is_file():
        return

    assets = directory / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        """A built file when one exists, else ``index.html`` for a client route."""
        parts = [part for part in full_path.split("/") if part]
        if not parts:
            return FileResponse(index)
        if parts[0] in _NON_SPA_SEGMENTS or any(part.startswith(".") for part in parts):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        root = directory.resolve()
        candidate = (root / full_path).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if candidate.is_file():
            return FileResponse(candidate)
        # A missing asset must not be papered over with the app shell: the
        # built asset directory and anything with a file extension are files,
        # not client routes.
        if parts[0] == "assets" or "." in parts[-1]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(index)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start telemetry for the server's lifetime and stop it on shutdown."""
    telemetry.start()
    try:
        yield
    finally:
        await telemetry.stop()


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()
    # Configure once per process; a test may call ``telemetry.configure(...)``
    # with in-memory collectors before building its own app.
    telemetry.get_telemetry()
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=_lifespan)
    app.openapi = build_openapi(app)
    app.include_router(health_router)
    app.include_router(orders_router)
    app.include_router(products_router)
    app.include_router(stock_router)
    register_error_handlers(app)
    telemetry.instrument_app(app)
    _mount_frontend(app, Path(settings.frontend_dist))
    return app


app = create_app()
