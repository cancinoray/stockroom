# Plan

Execution plan for the project phase. Specification: [product-spec.md](../product-spec.md).
Domain mechanics: [_docs/domain.md](domain.md). Team and process: [_docs/process.md](process.md).

## Assumptions

| | |
| --- | --- |
| Stack | FastAPI + PostgreSQL backend, React/Vite frontend, OpenAPI contract |
| Hosting | Fly.io for the app (dev + prod), managed Postgres, Grafana Cloud free tier for telemetry |
| Scope | Core six stories; stretch items only if Phase 5 ends early |
| Effort | ~24 focused hours (see [_docs/backlog.md](backlog.md) for the task-level estimates) plus ~3h of peer reviews, at roughly 2h per day |
| Dates | Written for a two-week window starting 2026-10-27. **Check the real deadline on the course platform and compress by cutting stretch work — never by cutting Phase 6 or 7.** |

## 1. Why this order

Five sequencing decisions, and the reason for each:

1. **Frontend prototype first, contract second, backend third.** This is the order the course
   teaches, and it is also what the rubric's top band for the contract asks for: an OpenAPI file
   that *fully reflects front-end requirements*. You can only guarantee that by deriving the
   contract from a real client with a mocked service layer. Writing the backend first produces a
   contract that describes what the backend does, not what the UI needs.
2. **Deploy a walking skeleton in Phase 1.** A `hello world` behind Fly + CI on day 3 proves the
   delivery pipe while there is nothing to lose. Teams that deploy in the last week discover
   secrets, regions and migrations with no time left. Phase 5 then hardens a working pipe instead
   of building one.
3. **Backend core before the real screens.** The prototype used a mock; the real client waits.
   The reservation transaction is the risky part, and the UI is mostly mechanical once the contract
   is frozen — so the risky part gets the slack.
4. **Integration tests during their phase, concurrency test in Phase 4.** Each phase ships unit
   tests for its own logic; the dedicated phase is where the *system-level* claims (concurrency,
   AC coverage, a browser walking the happy path) get proven.
5. **Observability after deployment, not before.** Telemetry needs a real environment to be
   meaningful, and traces of local unit tests teach nothing.

### Frontend-first guardrails

The prototype decides what the contract must carry, so it can quietly define the wrong product.
Five rules keep it honest:

1. **One module owns every backend call.** `frontend/src/api/` exposes a typed client; a mock
   implements the same interface. In P3 the mock is swapped for the real client and then deleted —
   no component ever knows which one it is talking to.
2. **The mock reproduces failure, not just success.** Each error the spec defines — per-line
   `409 insufficient_stock`, `409 invalid_transition`, `409 would_breach_reserved`, `422` — is a
   mockable case with a toggle. A mock that always succeeds means the error UI is written blind and
   never exercised.
3. **The UI is never a second source of truth for stock.** No local decrements, no optimistic
   counters. After a mutation, invalidate and refetch. A patched number is a UI that disagrees with
   the ledger.
4. **Every field maps to a spec concept.** If a screen wants something the product spec does not
   define, the field is dropped or the spec is amended through the PM. Prototypes invent data models
   cheerfully.
5. **The contract is derived, then audited.** Derive `openapi.yaml` from the client's calls, then
   walk all 24 acceptance criteria and confirm each has the shape and status code it needs. Where
   they disagree, fix the contract, not the criterion.

**Types are generated; behaviour is not.** `openapi-typescript` + `openapi-fetch` for the client,
Pydantic models from `components/schemas` for the backend. Routing, transactions and locking are
hand-built against the contract — a generator will not produce a reservation transaction, and
layering services over generated stubs costs more than it saves at thirteen endpoints.

## 2. Phases

| Phase | Work | Exit criteria | Rubric | h |
| --- | --- | --- | --- | --- |
| **P0** Spec & context | Problem statement, spec v1, invariants, agent team, `AGENTS.md`, docs router, tracker with 20+ issues | A stranger can read the spec and say what the app does and how it fails | 1–4 (8 pts) | 3 |
| **P1** Prototype, contract & skeleton | React prototype with a **mocked service layer**, `openapi.yaml` derived from it, backend skeleton, `Makefile`, lint, CI, **walking skeleton deployed to Fly dev** | `make dev` runs; a public URL serves a health check; CI green on PR; the contract matches the client's calls | 5, 9 | 4 |
| **P2** Backend core | Schema + Alembic + seed, domain service, reservation transaction, stock endpoints, invariant check, problem+json errors | Every backend AC has an integration test that passes; `/api/invariants` clean | 5 (2 pts) | 5 |
| **P3** Frontend | Swap the mocked layer for the generated client, inventory / place-order / orders screens, per-line error surfacing | Three screens work end to end against the deployed dev API, with no hand-written response types | 5 | 3 |
| **P4** Tests | Unit suite, integration suite, 20-way concurrency test, Playwright happy path + one failure path | `make test` green from a clean clone; concurrency test fails if locking is removed | 6 (2 pts) | 2 |
| **P5** Ship | Two-stage image (Node builds the frontend, FastAPI serves the static files), compose with DB, **build once to a registry then deploy by tag** (`YYYYMMDD-HHMMSS-shortsha`), prod environment + manual approval that promotes the *same image*, migrations on release, rollback rehearsal, deployment + release docs | `docker compose up --build` on a clean machine; merge → dev; approval → prod pulls the already-tested image; rollback demonstrated | 7–9 (7 pts) | 2 |
| **P6** Observability | OTel traces/metrics/logs with shared trace id, Grafana Cloud wiring, dashboard for the order journey, 3 alert rules carrying service, env, version, owner and dashboard URL, + runbooks | One trace id appears in traces, logs and metrics; an alert fires from injected user impact | 10–11 (3 pts) | 2 |
| **P7** On-call | `on-call-engineer/` poller (alert API every minute → headless agent), evidence collector, autonomy policy, response schema, **a realistic bug injected that the current tests pass** | Alert → evidence packet → diagnosis → fix PR → verified recovery, recorded in `on-call-engineer/incidents/` | 12 (2 pts) | 2 |
| **P8** Docs & demo | README final, screenshots, AI usage report, 3-minute video, submission | Reviewer can score all 12 criteria without asking a question | all | 1.5 |

Stretch, only after P5: **S1** idempotent order creation, **S2** multi-warehouse, **S3** load-test
report. Adding S1 is the best value for effort if there is a spare afternoon — it strengthens
criterion 5 and makes a better incident story.

## 3. Schedule

| Day | Date | Work | h |
| --- | --- | --- | --- |
| 1 | Mon 2026-10-27 | P0 — spec, agent team, docs, tracker | 3 |
| 2 | Tue 10-28 | P1 — React prototype with a mocked client | 2 |
| 3 | Wed 10-29 | P1 — `openapi.yaml` from the client, CI, walking skeleton on Fly | 2 |
| 4–5 | Thu 10-30 → Fri 10-31 | P2 — schema, reservation, endpoints | 5 |
| 6 | Sat 11-01 | P3 — three screens | 3 |
| 7 | Sun 11-02 | P4 — tests, concurrency proof | 2 |
| 8 | Mon 11-03 | P5 — containers, prod gate, rollback | 2 |
| 9 | Tue 11-04 | P6 — telemetry, dashboard, alerts | 2 |
| 10 | Wed 11-05 | P7 — poller, responder, injected-bug drill | 2 |
| 11 | Thu 11-06 | P8 — docs, video, submission | 1.5 |
| 12–13 | Fri 11-07 → Sun 11-09 | Buffer + **3 peer reviews** (mandatory) | 3 |

If a day slips, cut in this order: S1–S3 → frontend polish → P3's second screen → nothing else.
Deployment, observability and the responder are half the rubric; they are not the buffer.

## 4. Rubric target

| Criterion | Target | Notes |
| --- | --- | --- |
| Problem description | 2 | README written in P0 |
| Product specification | 2 | Spec + public board; the issue chain is the evidence |
| Agent team specification | 2 | `_docs/process.md` with roles, permissions, grooming, orchestrator + `_docs/team/*.md` |
| Context management | 2 | `AGENTS.md` router + `CLAUDE.md` + `_docs/` modules + discoverable skills and subagents |
| Application | 2 | `make dev` single command |
| Testing | 2 | Unit + integration + e2e, one command |
| Containerization | 2 | compose incl. database |
| Deployment | 2 | Public URL on Fly, dev and prod |
| CI/CD | 3 | Tests → deploy dev on merge → manual prod approval |
| Observability | 2 | Trace id shared across all three signals, viewable in Grafana |
| Alerting | 1 | Three rules, two on user impact |
| On-call agent | 2 | Recorded incident with a proposed, verified fix |
| **Total** | **23/24** | Passing threshold is 10. The realistic risk is CI/CD 3→2 and on-call 2→1, which still passes comfortably |

The plan deliberately over-invests relative to the 10-point threshold. The reason is not the score:
the operational half (9–12) is the part that is hard to fake, and it is the part this course is
actually about.

## 5. Risk register

| # | Risk | Likelihood | Impact | Mitigation | Trigger to act |
| --- | --- | --- | --- | --- | --- |
| R1 | Concurrency test flaky in CI | Medium | High — it is the headline claim | Barrier-based test, 50-iteration loop, `pytest -p no:randomly`, live uvicorn not TestClient, dedicated CI job | Any flake in 3 consecutive runs → investigate locking, do not retry-and-ignore |
| R2 | Grafana Cloud onboarding friction (keys, OTLP endpoint) | Medium | Medium | Local compose profile with Prometheus/Loki/Tempo as the fallback; the app only knows an OTLP endpoint from env | Stuck >45 min → switch to local stack and screenshot dashboards |
| R3 | Fly Postgres / billing surprise | Low | Medium | Managed Postgres on a free or cheap tier; keep the database DSN as a secret so the provider can change | Quota warning → migrate to another managed Postgres, app unchanged |
| R4 | Frontend polish eats the schedule | High | Medium | Three screens, no design system, Tailwind defaults; stop at "clear and usable" | P3 exceeds 3h → ship two screens, log the third as a v1.1 issue |
| R5 | Responder agent loops, costs, or breaks something | Medium | Medium | Bounded tool set, read-only credentials, isolated worktree, 10-minute budget, allowlisted actions, output schema validation | Two failed runs → record it as an incident with escalation, which still satisfies the criterion honestly |
| R6 | Deadline earlier than assumed | Medium | High | Phases are independently demoable; P0–P5 alone score 19/24 | Check the platform on day 1 and re-cut the schedule |

## 6. Demo script (3 minutes)

Record once, after P7. Each beat maps to a rubric row so a reviewer can score while watching.

| # | Show | Proves |
| --- | --- | --- |
| 1 | README on GitHub: problem, screens, correctness core | 1 — problem description |
| 2 | Project board filtered by `phase:2`, one issue open, then the PR that closed it | 2 — spec + tracker used by agents |
| 3 | `_docs/process.md` loop diagram, then the QA verdict comment on that PR | 3 — agent team |
| 4 | `AGENTS.md` → one doc link opens the exact domain rule | 4 — context management |
| 5 | `docker compose down -v && make dev`, browser opens; place an order with a short line → per-line `409`; fix the quantity → `201`; fulfil; stock drops | 5, 7 — app + single command |
| 6 | Terminal: `make test`, concurrency test log shows 1 × 201 / 19 × 409 | 6, and the headline claim |
| 7 | Merge a PR → Actions runs → dev deploy → approval → prod deploy → public URL reload | 8, 9 — deployment and CI/CD |
| 8 | Grafana: the trace for the order placed in beat 5, with logs and the metric for the same trace id | 10 — observability |
| 9 | Inject the failure flag, alert fires, responder runs, incident report + fix PR appear | 11, 12 — alerting and on-call |

## 7. Submission checklist

- [ ] Public GitHub repo with the tracker and board visible
- [ ] README states the problem, functionality and expected behaviour
- [ ] `product-spec.md` and `_docs/` complete; `_docs/ai-usage-report.md` current
- [ ] Deployed URL live (prod) and a dev environment
- [ ] `make dev` from a clean clone; `make test` green
- [ ] Demo video linked from the README
- [ ] Three peer reviews completed on the course platform — **mandatory, a missing review fails
      the project regardless of the build**
- [ ] Submission form filled before the deadline

## 8. What to confirm on the course platform

Three things this plan cannot read from the repository:

1. The exact submission deadline for the current attempt, and whether the second attempt is still
   available.
2. Whether the review workflow needs a specific submission field (repo URL, video URL, deployed
   URL) and a self-assessment.
3. Whether peer reviews are due before or after the submission deadline.
