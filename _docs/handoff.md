# Handoff

Everything a new session, a new agent, or a reviewer needs in order to continue without reading the
conversation that produced this repo. If you are an agent: read this, then `AGENTS.md`, then the one
document your task needs.

Last updated: 2026-10-27 · Status: **P1 in progress — skeleton and prototype built locally, not merged**
Repo: https://github.com/cancinoray/stockroom (public)

## 1. Status snapshot

| | |
| --- | --- |
| Phase | P1 in progress. T1.1 (backend skeleton) and T1.2 (mocked React prototype) are built and verified locally; T1.3 and T1.4 are next |
| Code | `backend/` (app factory, settings, `/healthz`, `/api/version`) and `frontend/` (mock-backed Inventory, Place order and Orders screens). No database, real API or contract yet |
| Commands | `make install`, `make run`, `make test` and `make lint` work. `make dev`, integration, migrations and e2e land with their phases |
| Tracker | Live: issues #1–#11 groomed with acceptance criteria, milestones P1 and P2. Issues are created per phase, just in time — a 7-day build should not groom work it may cut |
| Blocking on you | Fly.io token by D2, Grafana Cloud stack by D6; the course-platform deadline is still unconfirmed |
| Next action | T1.3 contract from the prototype's client, then T1.4 CI + Fly dev deploy |

## 2. What we are building and why it has this shape

Stockroom: order and inventory management for a single-warehouse distributor. Placed orders reserve
stock from one transaction, every quantity change is an append-only ledger row, and every count can
be explained from history. Six user stories, 24 acceptance criteria
([product-spec.md](../product-spec.md)).

The shape is deliberate. Inventory CRUD is easy and worth nothing here; the rubric concentrates
half its points in operations, and the interesting engineering is a **correctness core**:
all-or-nothing reservation under concurrency, and a ledger that makes drift detectable. Every
design decision below serves that, or serves finishing on time.

## 3. Decision log

The expensive-to-rediscover decisions. Changing one is a conversation, not a commit.

| # | Decision | Rejected alternative | Why |
| --- | --- | --- | --- |
| D1 | FastAPI + React/Vite + Postgres | Next.js full-stack, Django, Next+FastAPI | Pure-Python domain tests for the risky logic; no SSR failure modes in a dashboard; FE/BE split is what the contract criterion scores |
| D2 | Fly.io + Grafana Cloud free tier | AWS ECS/RDS + self-hosted stack | 2 points either way; managed OTel backend removes a whole stack to operate |
| D3 | 6 stories / 24 ACs | 10 stories, 4 stories | Covers all 12 criteria without breadth that no one scores |
| D4 | Movements are truth, `on_hand`/`reserved` are caches | Derive counters on every read | Hot-path reads stay cheap; drift becomes detectable rather than invisible, which also gives alert #3 |
| D5 | All-or-nothing reservation; no `pending` state | draft → pending → confirmed | Removes the partial-reservation bug class and the cleanup job it needs |
| D6 | `SELECT … ORDER BY sku FOR UPDATE` | Conditional `UPDATE … WHERE available >= qty` | Ordered locking is deadlock-free by construction; validate-then-write reads cleanly in a trace and yields per-line `409` |
| D7 | Sync SQLAlchemy + psycopg3, threads | Async SQLAlchemy + asyncpg | Shorter transaction code to review; the concurrency test uses a thread barrier against live uvicorn, so real threads are the honest test |
| D8 | Frontend prototype first, contract derived from its client | Contract first, then both sides | Rubric's top band: contract "fully reflects front-end requirements". Only derivable from a real client |
| D9 | Production is one container; FastAPI serves the built frontend | Separate frontend container/CDN | One URL, no CORS, one service to health-check. Dev still runs Vite + API separately |
| D10 | Build once, push a tagged image, promote that tag to prod | Rebuild on deploy | Otherwise prod is not the artifact dev tested |
| D11 | `_docs/` + four-section task template + `_docs/team/*` + `.agents/{agents,skills}` | Single long `AGENTS.md`, no role files | Context engineering: the agent loads only what the task needs; matches the course series so reviewers recognise it |
| D12 | Run the PM→SWE→QA graph from P2; P1 uses direct sessions | Graph from day one | The graph costs 2–3× tokens per issue. P1 is exploratory; P2 is where a self-graded agent would lie to you |
| D13 | No authentication | Demo login, bearer tokens | Not scored, and it would eat the observability budget. Deployment is a public demo with seeded data |
| D14 | `on-call-engineer/` (poller + responder), module-4 file names inside | `incident-response/` | Matches Part 4's directory; keeps the module deliverable names so reviewers find them |
| D15 | One typed mock seam in `frontend/src/api/`; screens never call `fetch` directly | Ad-hoc calls from components | T1.3 derives the contract from the seam; P3 swaps one module and no screen changes |

## 4. Where everything lives

| Concern | File |
| --- | --- |
| Behaviour, ACs, invariants, API surface | [product-spec.md](../product-spec.md) |
| Backend skeleton | `backend/` — app factory, settings, `/healthz`, `/api/version` |
| Frontend prototype | `frontend/src/` — three screens over the mock in `frontend/src/api/` |
| Front-end design system | [_docs/design-system.md](design-system.md) |
| Schema, ledger semantics, locking, invariant SQL | [_docs/domain.md](domain.md) |
| Roles, permissions, grooming, loop, orchestrator, worktrees | [_docs/process.md](process.md) |
| Issue template (Goal / AC / Out of scope / Constraints) | [_docs/task-template.md](task-template.md) |
| Phases, dates, risks, demo script, rubric target | [_docs/plan.md](plan.md) |
| Task list with estimates and AC ids | [_docs/backlog.md](backlog.md) |
| Role prompts | [_docs/team/](team/) · subagent defs in `.agents/agents/` |
| Repeatable procedures | `.agents/skills/add-migration/`, `.agents/skills/investigate-alert/` |
| Agent entry point | [AGENTS.md](../AGENTS.md) — tool-neutral, no vendor-specific config |
| Session-by-session AI log | [_docs/ai-usage-report.md](ai-usage-report.md) |

## 5. How work happens

**From P2, per issue** (the loop in [_docs/process.md](process.md) §4):

1. PM grooms the issue with the task template. You read it and correct a sentence if it is wrong.
2. Engineer implements in its own worktree: failing test → smallest change → PR with `Closes #N`.
3. QA verifies in a fresh context, against the running code, and posts `PASS`/`FAIL` per AC.
4. On `FAIL` the comment goes back to the engineer. Two cycles max, then a human decides.
5. You merge. CI has already run lint + unit + integration.
6. Merge builds one image, deploys dev, smoke-tests. You approve the same tag for prod.

**The exception, P1.** No graph. Direct sessions, one prompt at a time, you look at the browser after
each step: prototype → contract → skeleton → deploy. The process starts once there is something to
regress.

**What you personally own**: spec approval (P0), contract freeze (end of P1), every merge, prod
promotion, and the final rubric self-score before submission.

## 6. Open items

| # | Item | Owner | Blocks |
| --- | --- | --- | --- |
| O1 | Exact deadline on the course platform; re-cut the schedule if it is not ~2 weeks out | You | Schedule only |
| O2 | ~~Create the public repo, push, labels, groomed issues~~ — done: https://github.com/cancinoray/stockroom | Done | — |
| O3 | Fly.io account + API token, GHCR or Fly registry access | You | P1 deploy |
| O4 | Grafana Cloud free tier: stack + OTLP endpoint + token | You | P6 |
| O5 | Spec open questions Q1–Q3 (reorder point scope, `customer_ref`, partial fulfilment) | Defaults set in spec §9 | Nothing yet |
| O6 | Confirm whether `_docs/backlog.md` stays as a mirror after the tracker exists | You | Nothing (one file) |

## 7. Traps

1. **A concurrency test that passes for the wrong reason.** If the harness serialises requests, the
   test proves nothing. Mitigation: barrier + threadpool + live uvicorn, and verify it fails when
   `FOR UPDATE` is removed. This is the single most important test in the repo.
2. **`check (reserved <= on_hand)` turning a logic bug into a 500.** Under contention a wrong
   validation path surfaces as `IntegrityError`. Map it to `409` or to the drift report — and assert
   in the test that a `500` never appears.
3. **Contract drift.** FastAPI's generated schema quietly diverges from `openapi.yaml`. T1.3 adds a
   CI check comparing them; without it the contract becomes decoration.
4. **Alembic autogenerate misses what this schema depends on**: check constraints, the append-only
   trigger, partial indexes. Review every migration by hand (see the `add-migration` skill).
5. **Grafana Cloud retention.** Free-tier data expires; record the demo while the evidence is fresh,
   and do not plan a "look at last week's dashboard" beat in the video.
6. **Responder cost and looping.** Ten-minute budget, allowlisted read-only tools, no prod
   credentials. A responder that cannot conclude is an escalation packet, not a retry loop.
7. **Peer review is pass/fail.** Three reviews are mandatory; a great project with no reviews fails.
   Budget 3h and do them before the deadline, not after.

## 8. Next session: first 30 minutes

```bash
cd stockroom
git log --oneline          # latest: 35b5c87 tracker seeded, 7-day status
cat _docs/plan.md §2.1     # the dependency-ordered lanes
cat _docs/backlog.md       # 37 tasks; T1.3/T1.4 are next
```

T1.1 and T1.2 are built and verified locally but not merged. Review the diff, then run T1.3
(derive `openapi.yaml` from the prototype's mock client) and T1.4 (CI + Fly dev deploy). Do not
build the database until the contract is frozen.

## 9. Source coverage and what is unverified

The plan follows the five-part course article series (specifications and loop/graph engineering →
frontend-first build → containerize and deploy → observability and on-call → skills and subagents).
Two corrections came from reading those sections closely rather than skimming: production as a
**single container** (D9) and the **build-once/promote-by-tag** release (D10).

Unverified, and should be checked rather than assumed:

- The course-platform deadline and submission fields.
- That Fly.io and Grafana Cloud free tiers still cover this workload at your usage.
- Every estimate in the backlog. They are reasoned, not measured.
- The two skills: written but never executed. Their first real use is the test.
- The mocked prototype proves the UI flows, not the API. T1.3 derives the contract from it, and P2
  makes the backend match.
