# syntax=docker/dockerfile:1

# Two-stage production image (T5.1, issue #46).
#
# Stage 1 builds the React app with Node. Stage 2 is the Python runtime that
# serves the API and the built files from one container (handoff D9, D10): no
# Node, no npm, no `frontend/node_modules` and no `frontend/src` ship in it.

FROM node:22-alpine AS frontend

WORKDIR /app/frontend

# Dependencies first so source edits do not invalidate the install layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  UV_PROJECT_ENVIRONMENT=/app/.venv \
  PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so source edits do not invalidate the install layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Only the runtime sources and the built assets are copied. No `.env*` file, no
# test tree and no frontend source reach the final image (AC12).
COPY alembic.ini ./
COPY backend ./backend
COPY --from=frontend /app/frontend/dist ./frontend/dist

# The app keeps no writable state, so it runs unprivileged (AC11).
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin stockroom
USER stockroom

EXPOSE 8000

# Migrations, then the idempotent seed, then the server: a first run on an
# empty volume and a restart on a populated one both come up in that order.
CMD ["sh", "-c", "alembic upgrade head && python -m backend.db.seed && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]

# The compose stack relies on this image-level check (AC9).
HEALTHCHECK --interval=5s --timeout=5s --start-period=15s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)"
