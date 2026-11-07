UV_CACHE_DIR ?= .uv-cache
NPM_CACHE ?= .npm-cache
PORT ?= 8000
OBSERVABILITY_FILES = -f compose.yaml -f compose.observability.yaml $(if $(wildcard compose.override.yaml),-f compose.override.yaml)
export UV_CACHE_DIR

.PHONY: install dev run test test-unit test-frontend test-integration e2e lint lint-backend lint-frontend format migrate seed reset observability observability-down check-alerts oncall-poll

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

# Local observability stack: app + db plus the OpenTelemetry collector,
# Prometheus, Loki, Tempo, Alloy and Grafana. The profile is opt-in, so
# `make dev` still starts only app + db. The untracked local
# compose.override.yaml is appended only when present, which mirrors the same
# app port as `make dev`. `down` keeps the volumes, including `stockroom-db`.
observability:
	docker compose $(OBSERVABILITY_FILES) --profile observability up -d --build

observability-down:
	docker compose $(OBSERVABILITY_FILES) --profile observability down

# T6.3 (#57): the alert rules must parse before the stack loads them. `promtool`
# ships in the pinned Prometheus image from observability/README.md; the mount
# is read-only and no container or volume is kept.
check-alerts:
	docker run --rm --entrypoint promtool \
		-v "$(PWD)/observability:/rules:ro" \
		prom/prometheus:v3.16.0@sha256:e04987641b57704f408e31f6373ba4138ecf27cb4a165d24aabb6c38fddd0f06 \
		check rules /rules/alerts.yaml

# T7.1 (#61): the alert poller. GNU make parses `--once` as its own option, so
# the flag is forwarded through ARGS, not appended to the target:
#   make oncall-poll ARGS=--once
oncall-poll:
	uv run python on-call-engineer/poll_alerts.py $(ARGS)

# e2e: the browser journeys (place -> fulfil, short line, low stock, ledger).
# Needs Docker; Chromium is installed through Playwright when it is missing.
# The run starts its own stack under the `stockroom-e2e` Compose project on
# free ports, waits for /healthz, and tears it down with `down -v` on success
# and on failure. Run it again straight away: each run gets a fresh volume.
#   make e2e
#   make e2e E2E_BASE_URL=http://127.0.0.1:5173
# With E2E_BASE_URL set, no stack is started and the specs target that UI.
e2e:
	cd frontend && npx playwright install chromium
	E2E_BASE_URL="$(E2E_BASE_URL)" sh tests/e2e/run-e2e.sh
