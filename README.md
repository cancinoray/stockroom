# Stockroom

**Order and inventory management for a small distributor that sells from real stock.**

## The problem

A distributor with one warehouse and a few dozen SKUs sells through a spreadsheet and a chat
thread. Two people sell the same last unit, because availability is a number someone typed
yesterday. The warehouse finds out at pick time — after the customer was promised a delivery
date. And when the physical count disagrees with the sheet, nobody can say which sale, return or
damaged box caused the difference: the sheet only holds a total, not its history.

Stockroom replaces the sheet with a system where:

- availability is computed from the same rows that orders write to;
- an order reserves every line or reserves nothing;
- every change to a quantity is an append-only entry with a reason, an actor and a timestamp, so a count can be **explained** instead of trusted.

## What the app does

| Screen          | What you do there                                                                                                                        |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Inventory**   | On-hand, reserved and available per SKU; stock position chart; low-stock badges; receive or adjust stock with a required reason and note |
| **Place order** | Pick SKUs, see live availability, submit; if any line is short, the short lines are named individually                                   |
| **Orders**      | Filter by status, cancel or fulfil, and read the movement timeline for an order or a SKU                                                 |

## Screens

Captured from the running seeded stack at desktop width. The inventory shows both low-stock badges
and the shelf-position chart; the order ticket carries two real lines and their availability; the
order drawer shows the reservation in the movement timeline.

### Inventory

![Inventory screen: eight seeded SKUs with on-hand, reserved and available counts, the stock position chart, and low-stock badges on SKU-5127 and SKU-7714](_docs/screenshots/inventory.png)

### Place order

![Place order screen: an order ticket for customer reference CUST-DEMO with two lines, quantities and prices, beside the live availability list](_docs/screenshots/place-order.png)

### Orders

![Orders screen: the CUST-DEMO order detail drawer with line totals and the append-only movement timeline showing its reserve movement](_docs/screenshots/orders.png)

## Demo video

**Demo video (3 minutes)** — placeholder; T8.3 (#70) replaces this line with the URL. No link yet.

## The correctness core

Four rules the system enforces, and the tests that prove it. This is the part that is not CRUD.

1. **All-or-nothing reservation.** An order with three lines reserves all three or returns `409`
   naming each short line. No partial holds, no cleanup job for half-reserved orders.
2. **No oversell under concurrency.** Twenty simultaneous orders for the last unit produce one
   `201` and nineteen `409`. Enforced by one transaction that locks stock rows in SKU order, so
   it cannot deadlock itself.
3. **Append-only ledger.** `on_hand` and `reserved` are caches, not the truth. The ledger is:
   `on_hand == Σ delta_on_hand` and `reserved == Σ delta_reserved`. Drift is detectable, reported
   by `/api/invariants`, and alerts.
4. **Explainable counts.** Every movement carries a reason (`receive`, `adjust`, `reserve`,
   `release`, `ship`), an actor and a note. No endpoint updates or deletes a movement — not even
   for admins.

## Architecture

| Layer        | Choice                                                                                                      |
| ------------ | ----------------------------------------------------------------------------------------------------------- |
| Frontend     | React 19 + TypeScript + Vite + TanStack Query + Tailwind                                                    |
| API contract | `openapi.yaml` is the source of truth; the frontend client is generated from it                             |
| Backend      | FastAPI + SQLAlchemy 2 + Alembic, Pydantic v2                                                               |
| Database     | PostgreSQL 16 (Docker Compose locally or on a self-hosted host)                                             |
| Tests        | pytest (unit + integration against real Postgres) · vitest · Playwright                                     |
| CI/CD        | GitHub Actions → lint, tests, contract and container build; deployment is a manual self-hosted compose step |
| Telemetry    | OpenTelemetry → local `make observability` stack (Collector, Prometheus, Loki, Tempo, Alloy, Grafana)       |
| Operations   | Alert on user impact → bounded evidence packet → responder agent proposes a fix                             |

**Deployment topology.** Development runs Vite and FastAPI as two processes. Production is **one
container**: the frontend is compiled at image-build time (Node stage) and the resulting static
files are served by FastAPI. One URL, no CORS, no second service to deploy or health-check. It runs
on any Docker host; there is no managed platform dependency.

```mermaid
flowchart LR
    Browser["Browser"]

    subgraph App["one production container"]
        API["FastAPI: /api and static files"]
        Assets["React static assets (built in the Node stage)"]
        API -->|serves| Assets
    end

    subgraph Obs["local observability stack: make observability"]
        Collector["OpenTelemetry Collector"]
        Tempo["Tempo: traces"]
        Prometheus["Prometheus: metrics"]
        Alloy["Alloy: logs"]
        Loki["Loki: logs"]
        Grafana["Grafana: dashboard"]
    end

    Browser -->|"HTTP: one origin, no CORS"| API
    API -->|"reservation transaction: lock stock rows in ascending SKU order, then validate"| DB[("PostgreSQL 16")]
    API -->|"append-only ledger: INSERT one movement per change"| DB
    API -->|"OTLP/HTTP"| Collector
    API -->|"JSON stdout"| Alloy
    Collector -->|traces| Tempo
    Collector -->|metrics| Prometheus
    Alloy -->|logs| Loki
    Tempo --> Grafana
    Prometheus --> Grafana
    Loki --> Grafana
```

## Status

**Phase 7 is complete; Phase 8 (docs and demo) is in progress.** P1–P7 are merged: the app on the
real API, the unit/integration/concurrency/e2e suites, the one-container release image, the local
observability stack and the on-call drill. P1–P7 leave 0 open issues. Phase 8 is the three tasks in
the tracker: final README and screenshots (#68), reports and handoff (#69), and the demo video,
peer reviews and submission (#70).

The original seven-day build window ended on 2026-11-03; it never included a confirmed course
platform deadline. That deadline is still open question O1 in
[_docs/handoff.md](_docs/handoff.md), so the extra days buy review time, not new scope.

|            |                                                                                               |
| ---------- | --------------------------------------------------------------------------------------------- |
| Repo       | https://github.com/cancinoray/stockroom                                                       |
| Tracker    | P1–P7 issues closed (0 open); #68–#70 are the open Phase 8 tasks                              |
| Built      | Backend, generated client, three screens, and unit/integration/concurrency/e2e suites         |
| Next       | Phase 8: README/screenshots (#68), reports and handoff (#69), demo video and submission (#70) |
| Deployment | Local and self-hosted `docker compose`; one container, no managed platform                    |

## Run it locally

Docker is the supported path: one command brings up Postgres and the app with a migrated, seeded
database. The native backend path below is optional.

### Prerequisites

Docker with Compose for `make dev`; `uv`, Node 20+ and GNU make for tests, lint and the frontend.

### One command

```bash
make dev
```

`make dev` builds the image, starts Postgres and the app container (FastAPI plus the built React
assets), applies the Alembic migrations and seeds one `MAIN` warehouse with 8 products and 8 opening
`receive` movements. The app is at `http://localhost:8000`; the UI and `/api` share that origin:

```bash
curl http://localhost:8000/healthz
# {"status":"ok","db":"ok"}
```

`make dev` runs in the foreground; stop it with Ctrl-C, then `docker compose down`.

### Frontend (development)

The production image already contains the built frontend, so `make dev` needs no Node process. For
UI work, run Vite against the running API:

```bash
cd frontend
npm ci
VITE_API_BASE_URL=http://localhost:8000 npm run dev   # http://localhost:5173
```

The screens use the generated `openapi-fetch` client in `frontend/src/api/` against the real API.
`VITE_API_BASE_URL` points the Vite dev server at the stack; the built app calls same-origin `/api`.
Vite is a development-only process — production serves the compiled assets from the one container.

If the stack is on another port, use that origin: `VITE_API_BASE_URL=http://localhost:18000 npm run dev`.

### Tests and lint

Run `make install` once first (`uv sync` + `npm ci`), then:

```bash
make test             # backend unit suite + frontend vitest
make test-integration # httpx against a real Postgres; starts its own disposable postgres:16
make lint             # ruff, ruff format --check, tsc, eslint
```

`make test-integration` needs Docker because the harness starts a throwaway `postgres:16`
container and removes it afterwards. Point `STOCKROOM_TEST_DATABASE_URL` at an empty, disposable
database to reuse one instead.

### Data, stopping and ports

Seeding is idempotent and runs on every `make dev`, so restarting adds nothing. To wipe the
database and reseed from scratch:

```bash
docker compose down -v
make dev
```

`docker compose down` stops the stack and keeps the `stockroom-db` volume; `down -v` deletes it.
`make seed` and `make reset` are optional: they need an explicit `STOCKROOM_DATABASE_URL` pointed
at a running database.

If port 8000 is taken, create an untracked, local-only `compose.override.yaml` in the repo root:

```yaml
services:
  app:
    ports: !override
      - "18000:8000"
```

Then `make dev` serves the app on `http://localhost:18000`. `!override` replaces the base port
mapping instead of adding a second one. Delete the file to go back to 8000.

### Native backend (optional)

```bash
make install
export STOCKROOM_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/stockroom
make migrate
make run           # uvicorn --reload on :8000 (PORT=8011 make run to change)
```

Migrations and `backend.db.seed` also work against that database. Docker remains the supported
one-command path.

## Documentation

| Doc                                                        | Contents                                                                   |
| ---------------------------------------------------------- | -------------------------------------------------------------------------- |
| [_docs/handoff.md](_docs/handoff.md)                       | Where the project stands, the decision log, the traps, the next action     |
| [product-spec.md](product-spec.md)                         | Problem, users, user stories, acceptance criteria, API surface, non-goals  |
| [_docs/domain.md](_docs/domain.md)                         | Data model, ledger, locking strategy, invariants as code                   |
| [_docs/process.md](_docs/process.md)                       | Agent team, grooming, the loop, the orchestrator, definition of done       |
| [_docs/design-system.md](_docs/design-system.md)           | Front-end tokens, components, responsive and accessibility rules           |
| [_docs/deployment.md](_docs/deployment.md)                 | One-container topology, the two environments, start and health checks      |
| [_docs/release-process.md](_docs/release-process.md)       | Build once, tag, pull, migrate, swap, smoke and roll back                  |
| [_docs/testing-guidelines.md](_docs/testing-guidelines.md) | Which suite owns which claim, and how to run it                            |
| [_docs/runbooks/](_docs/runbooks/)                         | Alert runbooks: invariant drift, error rate and p95 latency                |
| [_docs/team/](_docs/team/)                                 | Role definitions for the PM, engineer, QA and on-call agents               |
| [_docs/task-template.md](_docs/task-template.md)           | The four sections every issue must have before it is worked on             |
| [_docs/plan.md](_docs/plan.md)                             | Phases, schedule, risk register, demo script                               |
| [_docs/backlog.md](_docs/backlog.md)                       | Tasks with acceptance criteria and estimates                               |
| [_docs/ai-usage-report.md](_docs/ai-usage-report.md)       | How AI tools were used, reviewed and verified                              |
| [observability/](observability/)                           | Local collector, Prometheus, Loki, Tempo, Alloy, Grafana and alert rules   |
| [on-call-engineer/](on-call-engineer/)                     | Alert poller, evidence collector, responder, autonomy policy and incidents |
| [AGENTS.md](AGENTS.md)                                     | Entry point for any coding agent working in this repo                      |
| [.agents/](.agents/)                                       | Tool-neutral subagent definitions and project skills                       |

## Non-goals

Authentication and multi-tenancy, payments, purchase orders and supplier management, multiple
warehouses, returns/refunds, currency conversion, barcode scanning, and mobile apps. Each is
listed with a reason in [product-spec.md §8](product-spec.md#8-non-goals). The deployment is a
local or self-hosted demo with seeded, non-sensitive data.

## How this maps to the course rubric

Reviewers can score the project from this table.

| Criterion                | Evidence                                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------------------- |
| Problem description      | This README                                                                                                    |
| Product specification    | [product-spec.md](product-spec.md) + GitHub Issues/Project board (every issue carries its acceptance criteria) |
| Agent team specification | [_docs/process.md](_docs/process.md) + [_docs/team/](_docs/team/) + `.agents/agents/`                          |
| Context management       | [AGENTS.md](AGENTS.md) routing to `_docs/` modules, plus discoverable skills and subagents                     |
| Application              | Three screens (see [Screens](#screens)), FastAPI backend, Postgres; `make dev`                                 |
| Testing                  | `make test` (unit + frontend), `make test-integration` (real Postgres) and `make e2e` (Playwright)             |
| Containerization         | `docker compose up --build` runs app + database                                                                |
| Deployment               | Local and self-hosted `docker compose`; no managed platform                                                    |
| CI/CD                    | `.github/workflows/ci.yml`: lint, tests, contract and container build; deployment is a manual self-hosted step |
| Observability            | `make observability` local stack and provisioned Grafana dashboard; trace ID in every log and error            |
| Alerting                 | `observability/alerts.yaml` + [_docs/runbooks/](_docs/runbooks/)                                               |
| On-call agent            | `on-call-engineer/` poller and responder + recorded incidents in `on-call-engineer/incidents/`                 |

Every row above is backed by a file or command in this repository.
