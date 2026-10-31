UV_CACHE_DIR ?= .uv-cache
NPM_CACHE ?= .npm-cache
PORT ?= 8000
export UV_CACHE_DIR

.PHONY: install dev run test test-unit test-frontend test-integration lint lint-backend lint-frontend format migrate seed reset

install:
	uv sync
	cd frontend && npm ci --cache ../$(NPM_CACHE)

run:
	uv run uvicorn backend.main:app --reload --port $(PORT)

test-unit:
	uv run pytest tests/unit

test-integration:
	uv run pytest tests/integration

test-frontend:
	cd frontend && npm test

# Integration and e2e suites land with their phases.
test: test-unit test-frontend

lint: lint-backend lint-frontend

lint-backend:
	uv run ruff check backend tests
	uv run ruff format --check backend tests

lint-frontend:
	cd frontend && npm run typecheck
	cd frontend && npm run lint

format:
	uv run ruff format backend tests

migrate:
	uv run alembic upgrade head

seed:
	uv run python -m backend.db.seed

reset:
	uv run alembic downgrade base && uv run alembic upgrade head && uv run python -m backend.db.seed

# One-command local stack for the README's promise: build the dev image, start
# Postgres and the app, and let the app's command run migrations.
dev:
	docker compose up --build
