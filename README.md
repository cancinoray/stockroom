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

| Screen | What you do there |
| --- | --- |
| **Inventory** | On-hand, reserved and available per SKU; low-stock badges; receive or adjust stock with a required reason and note |
| **Place order** | Pick SKUs, see live availability, submit; if any line is short, the short lines are named individually |
| **Orders** | Filter by status, cancel or fulfil, and read the movement timeline for an order or a SKU |

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

| Layer | Choice |
| --- | --- |
| Frontend | React 19 + TypeScript + Vite + TanStack Query + Tailwind |
| API contract | `openapi.yaml` is the source of truth; the frontend client is generated from it |
| Backend | FastAPI + SQLAlchemy 2 + Alembic, Pydantic v2 |
| Database | PostgreSQL 16 (compose locally, managed Postgres in the cloud) |
| Tests | pytest (unit + integration against real Postgres) · vitest · Playwright |
| CI/CD | GitHub Actions → auto-deploy `dev` on merge → production behind manual approval |
| Telemetry | OpenTelemetry → Grafana Cloud (Prometheus, Loki, Tempo) |
| Operations | Alert on user impact → bounded evidence packet → responder agent proposes a fix |

## Status

**Specification phase.** The application is not built yet. Planned order of work, dates and
risks live in [_docs/plan.md](_docs/plan.md).

## Documentation

| Doc | Contents |
| --- | --- |
| [product-spec.md](product-spec.md) | Problem, users, user stories, acceptance criteria, API surface, non-goals |
| [_docs/domain.md](_docs/domain.md) | Data model, ledger, locking strategy, invariants as code |
| [_docs/process.md](_docs/process.md) | Agent team, grooming, the loop, the orchestrator, definition of done |
| [_docs/team/](_docs/team/) | Role definitions for the PM, engineer, QA and on-call agents |
| [_docs/task-template.md](_docs/task-template.md) | The four sections every issue must have before it is worked on |
| [_docs/plan.md](_docs/plan.md) | Phases, schedule, risk register, demo script |
| [_docs/backlog.md](_docs/backlog.md) | Tasks with acceptance criteria and estimates |
| [_docs/ai-usage-report.md](_docs/ai-usage-report.md) | How AI tools were used, reviewed and verified |
| [AGENTS.md](AGENTS.md) | Entry point for coding agents working in this repo |
| [CLAUDE.md](CLAUDE.md) | Claude Code entry point (imports `AGENTS.md`) |
| [.agents/](.agents/) | Discoverable subagent definitions and project skills, symlinked into `.claude/` |

## Non-goals

Authentication and multi-tenancy, payments, purchase orders and supplier management, multiple
warehouses, returns/refunds, currency conversion, barcode scanning, and mobile apps. Each is
listed with a reason in [product-spec.md §8](product-spec.md#8-non-goals). The production
deployment is a public demo with seeded, non-sensitive data.

## How this maps to the course rubric

Reviewers can score the project from this table.

| Criterion | Evidence |
| --- | --- |
| Problem description | This README |
| Product specification | [product-spec.md](product-spec.md) + GitHub Issues/Project board (every issue carries its acceptance criteria) |
| Agent team specification | [_docs/process.md](_docs/process.md) + [_docs/team/](_docs/team/) + `.agents/agents/` |
| Context management | [AGENTS.md](AGENTS.md) routing to `_docs/` modules, plus discoverable skills and subagents |
| Application | Three screens, FastAPI backend, Postgres; `make dev` |
| Testing | `make test` — unit + integration (real Postgres) + Playwright |
| Containerization | `docker compose up --build` runs app + database |
| Deployment | Public URL (Fly.io), see `_docs/deployment.md` |
| CI/CD | `.github/workflows/ci.yml` + `deploy.yml`, dev auto, prod manual approval |
| Observability | `observability/` + Grafana dashboard link, trace ID in every log and error |
| Alerting | `observability/alerts.yaml` + runbooks |
| On-call agent | `on-call-engineer/` poller and responder + a recorded incident in `on-call-engineer/incidents/` |

Sections marked *planned* are filled in as the phases complete; see [_docs/plan.md](_docs/plan.md).
