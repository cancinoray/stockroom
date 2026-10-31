# Local dev image for `make dev` and the CI container build.
# The two-stage production image (frontend build + static serving) is T5.1.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so source edits do not invalidate the install layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8000

# Migrations run before the server so a fresh volume is usable. The compose
# stack repeats this command explicitly; the image stays runnable on its own.
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
