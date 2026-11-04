# AI Usage Report

What AI did, what I checked, and what I overruled. One entry per working session, written by
whoever did the work (human or agent) before the session is considered finished.

The rule: an entry says what was **verified**, not what was **produced**. "Generated a
Dockerfile" is not an entry; "generated a Dockerfile, built it, ran the app from it, and removed
the build-only layer that leaked a token into the image" is.

## Session log

| #   | Date       | Phase | Tool / agent                                           | Task                                                                                       | Produced                                                                                                                                                                                                            | Verified how                                                                                                                                                                                                                 | Overruled / changed |
| --- | ---------- | ----- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| 1   | 2026-10-27 | P0    | AI coding agent (planning session)                     | Scope the project, write spec and process                                                  | README, product-spec, AGENTS.md, domain/process/plan/backlog docs                                                                                                                                                   | Rubric read from the course repo; starter repo inspected; estimates reconciled against phase totals                                                                                                                          | See notes below     |
| 2   | 2026-10-27 | P0    | AI coding agent (planning session)                     | Align the repo with the course article series (parts 1–5)                                  | `_docs/` layout, task template, team roles, `.agents/agents` + `.agents/skills`, reworked process and plan                                                                                                          | Each article read in the primary source; conventions cross-checked against the rubric wording; links and paths verified                                                                                                      | See notes below     |
| 3   | _pending_  | P0    |                                                        | Tracker setup (T0.4)                                                                       |                                                                                                                                                                                                                     |                                                                                                                                                                                                                              |                     |
| 4   | 2026-10-27 | P0    | AI coding agent (repo cleanup)                         | Remove the vendor-specific agent entry point                                               | Vendor-specific entry file and symlink tree removed; docs point only at `AGENTS.md` and `.agents/`                                                                                                                  | Repo-wide search for the vendor name returns nothing; every documented path resolves                                                                                                                                         | See notes below     |
| 5   | 2026-10-27 | P0    | AI coding agent (process)                              | Make concurrent multi-agent execution explicit and break the plan into dispatchable tasks  | `_docs/process.md` concurrency rules; `_docs/plan.md` §2.1 task map                                                                                                                                                 | Every task id checked against `_docs/backlog.md`; lane order checked against phase dependencies and the D5–D6 schedule                                                                                                       | See notes below     |
| 6   | 2026-10-27 | P1    | AI coding agent (backend subagent + parent)            | Build T1.1 backend skeleton and T1.2 mocked React prototype                                | FastAPI app factory/settings/health/version + tests; Vite/React/Tailwind/TanStack mock-backed Inventory, Place order and Orders; Makefile targets                                                                   | `make lint` and `make test` (2 backend, 7 frontend); production build; Playwright drove the short-line 409, fulfil, cancel and a 390px viewport; screenshots reviewed                                                        | See notes below     |
| 7   | 2026-10-27 | P1    | AI coding agent (UI)                                   | Add a per-SKU stock chart to the Inventory screen                                          | `StockChart` component, chart styling and Inventory integration                                                                                                                                                     | `npm run lint`, `npm run build`, `npm test`; measured bar widths in the running dev server; desktop and 390px screenshots reviewed                                                                                           | See notes below     |
| 8   | 2026-10-27 | P1    | AI coding agent (design)                               | Document the implemented front-end design as a reusable system                             | `_docs/design-system.md`; README, AGENTS and handoff links                                                                                                                                                          | Tokens cross-checked against `index.css`; component rules checked against the screens and the live dev server at 1440px and 390px                                                                                            | See notes below     |
| 9   | 2026-10-27 | P1    | AI coding agent (UI fixes)                             | Close the modal-focus and quantity-validation gaps                                         | Shared focus-trap hook, order-line validation, two regression tests, test cleanup                                                                                                                                   | `make lint`, `make test` (9 frontend) and production build; focus trap/restore exercised in jsdom                                                                                                                            | See notes below     |
| 10  | 2026-10-31 | P1–P2 | AI coding agent (orchestrator + four PM subagents)     | Groom every open issue, reconcile the backlog mirror, dispatch #3/#5/#7                    | Groomed tracker #1–#12 (#12 filed), `_docs/backlog.md` mirror, three worktrees on `feat/3-*`, `feat/5-*`, `feat/7-*`                                                                                                | Every edited issue re-read with `gh issue view`; AC count and seed size counted from the spec/domain, not the issues; `make test` (2 backend, 9 frontend) green at `b6de97a`; `git worktree list`                            | See notes below     |
| 11  | 2026-10-31 | P1–P2 | AI coding agent (orchestrator + engineer/QA subagents) | Merge the first batch, verify `main`, dispatch and review #4                               | Six PRs merged; five worktrees removed; #4 PR #19 (CI, compose, conditional deploy) with QA verdict                                                                                                                 | `make install`, `make lint`, `make test` (57 unit + 10 frontend) and `make test-integration` (15) on `763ad83`; QA #4 compose smoke `200 db: ok`; CI run 41177592538 green; `gh issue list`                                  | See notes below     |
| 12  | 2026-10-31 | all   | AI coding agent (process)                              | Make post-merge closure a QA responsibility                                                | AGENTS rule 10, process role/permissions/§5/§6/§9, QA and engineer role defs, handoff, `Refs` convention                                                                                                            | Grepped every role doc for contradictory close guidance; checked that #19/#21 already use `Refs`; docs-only diff                                                                                                             | See notes below     |
| 13  | 2026-10-31 | P1–P2 | AI coding agent (orchestrator + QA subagent)           | Narrow rule 8, merge #19/#21, post-merge close #6                                          | AGENTS rule 8, process §2/§6/handoff, backlog status; merged T1.4 and T2.2                                                                                                                                          | `main` 59ba86f: 57 unit + 10 frontend + 20 integration; CI green; post-merge QA closed #6; #4 left open                                                                                                                      | See notes below     |
| 14  | 2026-11-01 | P2    | AI coding agent (software-engineer subagent)           | Implement #8: reservation transaction + `POST /api/orders`                                 | `backend/api/orders.py`, `backend/api/problems.py`, `backend/domain/reservation.py`, router registration, unit + integration tests                                                                                  | `make lint`; 30 unit; 25 integration; `uv run pytest tests/integration -k reserve` 5 passed; domain purity and direct-SQL I5/I6 checks                                                                                       | See notes below     |
| 15  | 2026-11-01 | all   | AI coding agent (orchestrator + QA subagent)           | Make QA own the merge and close; require a fresh `origin/main` base; execute #8            | AGENTS rules 8/10, process §1/§2/§4–§9/§11/§12, QA and engineer role defs, `.agents/` defs, handoff, plan; #8 merged and closed                                                                                     | Re-read role docs after the change; QA rebased on `a33a96d` (28 integration, 64 unit, ruff clean); CI green on PR #22; post-merge proof at `90f4a43` (28 integration, 64 unit, 10 frontend, lint clean); #8 CLOSED           | See notes below     |
| 16  | 2026-11-01 | P2    | AI coding agent (software engineer)                    | Finish #9: stock endpoints, product catalogue, movements and the invariant report          | `backend/api/stock.py`, `backend/api/products.py`, router registration, `tests/integration/test_stock.py`; removed the unusable partial `backend/api/invariants.py`                                                 | Rebased on `origin/main` `148005d`; `make lint` clean; `make test` 64 unit + 10 frontend; `make test-integration` 55 passed (27 new); contract/route checks and a corrupted-cache 200 proven                                 | See notes below     |
| 17  | 2026-11-01 | P2    | AI coding agent (QA subagent)                          | Independently verify #9, merge PR #23 and close the issue                                  | `tests/integration/test_stock_qa.py` (19 tests); PASS and post-merge PASS comments; squash merge `cfb50fa`; #9 closed                                                                                               | 74 integration + 64 unit + 10 frontend; CI green; nine revert checks; post-merge proof at `cfb50fa`; `gh issue view 9` CLOSED                                                                                                | See notes below     |
| 18  | 2026-11-03 | P2    | AI coding agent (software engineer)                    | Implement #10: order list, detail, cancel and fulfil                                       | `backend/api/orders.py` (list/detail/cancel/fulfil), 9 tests appended to `tests/integration/test_orders.py`                                                                                                         | `make lint`; 64 unit + 10 frontend; `make test-integration` 83 passed; `uv run pytest tests/integration -k orders` 19 passed; concurrent double-cancel proof                                                                 | See notes below     |
| 19  | 2026-11-03 | P2    | AI coding agent (QA subagent)                          | Independently verify #10, merge PR #25 and close the issue                                 | `tests/integration/test_orders_lifecycle_qa.py` (6 tests); PASS and post-merge PASS comments; squash merge `4069ab6`; #10 closed                                                                                    | 89 integration + 64 unit + 10 frontend; CI green; five revert checks; post-merge proof at `4069ab6`; `gh issue view 10` CLOSED                                                                                               | See notes below     |
| 20  | 2026-11-03 | P2    | AI coding agent (software engineer)                    | Implement #11: problem+json error model with trace ids                                     | `backend/api/errors.py`, request-scoped ids in `backend/api/problems.py`, handlers in `backend/main.py`, sanitised health log, `ValidationProblemError` in `openapi.yaml`, 13 tests                                 | `make lint`; 64 unit + 10 frontend; 102 integration; 13 error tests; spectral clean; red-first failures before the handlers                                                                                                  | See notes below     |
| 21  | 2026-11-03 | P2    | AI coding agent (QA subagent)                          | Independently verify #11, merge PR #26 and close the issue                                 | `tests/integration/test_errors_qa.py` (18 tests); PASS and post-merge PASS comments; squash merge `a95bef8`; #11 closed                                                                                             | 120 integration + 64 unit + 10 frontend; CI green; four revert checks; post-merge proof at `a95bef8`; `gh issue view 11` CLOSED                                                                                              | See notes below     |
| 22  | 2026-11-03 | all   | AI coding agent (orchestrator)                         | Remove the managed deployment path; make the project local/self-hosted Docker Compose only | Deleted the managed-platform config; removed both deploy jobs from CI; rewrote deployment language in README, plan, handoff, backlog, process and AGENTS; rewrote issue #4; rebased and merged PR #24; QA closed #4 | A provider-name search over tracked files has no operational hits (only a base64 integrity false positive); `git diff --check` clean; CI runs on push and PR #24 CI is green; #4 PASS and closed; PR #24 merged at `f13b6e8` | See notes below     |
| 23  | 2026-11-04 | P3    | AI coding agent (software engineer)                    | Implement #27: generated client, hooks, normalizer and contract check                      | Generated schema, typed `openapi-fetch` client, hook surface, problem normalizer, contract-check script and CI step; 38 frontend tests                                                                              | `generate:api` reproducible; `check:contract` 0 after #32; typecheck/lint clean; existing screen tests unchanged; CI green after rebase                                                                                      | See notes below     |
| 24  | 2026-11-04 | P2    | AI coding agent (software engineer)                    | Implement #32: align FastAPI generated OpenAPI with the frozen contract                    | Request/response models, `{id}` paths, declared 201s, problem responses, `Health`/`Version`; contract check 70 → 0 differences                                                                                      | `check:contract` exit 0; red path demonstrated; 120 integration; 74 unit + 10 frontend; lint clean                                                                                                                           | See notes below     |
| 25  | 2026-11-04 | P2–P3 | AI coding agent (QA subagents)                         | Verify/merge #32 and #27; unblock and close T3.1                                           | QA PASS comments; `tests/unit/test_openapi_contract_qa.py` and `frontend/src/api/index.test.ts`; merges `d620514` and `83445b2`; #32/#27 closed                                                                     | 0 contract differences on `main`; 120 integration; 74 unit + 40 frontend; revert checks; CI green; `gh issue view 27/32` CLOSED                                                                                              | See notes below     |
| 26  | 2026-11-04 | P3    | AI coding agent (three engineers + QA subagents)       | Implement T3.2–T3.4 screens in parallel; verify, merge and close                           | Inventory, place-order and orders screens on real hooks; QA test files; merges `116cad0`, `af96966` and `8a6eeb8`; #28–#30 closed; #37 resolved                                                                     | CI green on all three; final 74 backend + 90 frontend / 1 skipped; QA revert checks on every screen; post-merge proofs at each merge commit                                                                                  | See notes below     |
| 27  | 2026-11-04 | P4    | AI coding agent (PM + four engineers + QA subagents)   | Groom, implement, verify and merge T4.1–T4.4 in parallel                                   | Unit gaps + `_docs/testing-guidelines.md`; integration audit; 50×20 concurrency proof; Playwright journeys + `make e2e`; merges `857984b`, `e0971aa`, `4c22aa6`, `22981e2`; #38–#41 closed                          | Final 97 unit + 91 frontend + 124 integration + 4 e2e; CI green; red proofs and post-merge proofs; `gh issue view 38–41` CLOSED                                                                                              | See notes below     |

## Session 1 — 2026-10-27: scoping and specification

**What I asked for.** A project plan for an order-and-inventory system that would pass the course
rubric, starting from nothing.

**What AI did.**

- Fetched the course `project/README.md`, the docs-site project page and the archived 2025 page, and
  extracted the 12 criteria and their point bands.
- Fetched Modules 1–4 to align the plan with the taught workflow (spec → contract → backend →
  frontend → tests → containers → deploy → observe → responder).
- Checked whether the instructor's `order-tracker` starter could serve as a base, and concluded it
  could not (SQLite, static HTML, no contract, no framework frontend) but that its
  incident-response layout is worth copying.
- Proposed three stacks and two hostings with tradeoffs, and a six-story scope.

**What I verified myself, rather than trusting.**

- The rubric text: read in the primary source, not from a summary. The 24-point total and the
  10-point pass mark drive the whole plan.
- That Render, Railway and Cloud Run are acceptable deployment targets (Module 3 states this
  explicitly), so skipping AWS does not cost points.
- That the `order-tracker` repository actually exists and what is in it (file tree inspected) — a
  hallucinated starter would have wrecked the Phase 7 plan.
- That the toolchain is present locally: `python 3.12`, `node 26`, `uv`, `docker`, `git`.

**What I overruled.**

- **AWS ECS + RDS.** The course teaches it, but for a 24-hour budget the Terraform and IAM
  overhead buys no rubric points. Deployment is 2 points either way.
- **Next.js as the frontend.** One codebase sounds simpler, but it weakens the frontend/backend
  contract story the rubric scores, and server components add failure modes to a dashboard app.
- **Idempotency in the MVP.** Attractive but not free: it is now stretch task S1, because the
  six core stories already cover the rubric.
- **A "pending" order state.** Tempting to model a draft order, but all-or-nothing reservation
  removes the state and the partial-reservation bug class with it.

**Known gaps at the end of this session.**

- The course platform deadline has not been checked; the schedule assumes a two-week window.
- No code exists yet. `make dev` and `make test` are a documented contract, not working targets.
- Estimates are estimates: 24.5h of tasks against a 20h target is a deliberate overshoot, with the
  cut order written down in `_docs/plan.md §3`.

## Session 2 — 2026-10-27: aligning with the course series

**What I asked for.** Check the plan against the five-part series and fix what it gets wrong.

**What AI did.**

- Fetched all five articles. Part 1 and Part 4 indexes disagreed about Part 5 ("TBA" versus a link),
  so it fetched both indexes and confirmed Part 5 exists.
- Extracted each article to plain text, because the HTML fetch truncated mid-article and the
  sections that mattered (alerting, on-call, skills, subagents) were at the end.
- Compared conventions and applied the gaps: `_docs/` instead of `docs/`, the four-section task
  template, `_docs/team/*.md`, `.agents/agents` and `.agents/skills`, the orchestrator lifecycle,
  grooming as a gate.
- Reordered the build to frontend prototype → contract from the client → backend, and rewrote
  `_docs/process.md` around grooming, the QA verdict format, the orchestrator and parallel
  worktrees.

**Verified myself.**

- The rubric wording again, rather than the article's paraphrase: criterion 5's top band asks for a
  contract that "fully reflects front-end requirements", which is what makes frontend-first the
  better order and not just the taught one.
- That Part 5 really exists and is the skills/subagents article (two indexes checked).
- That the `.agents/` paths resolve and no stale `docs/` path remains anywhere in the repo.

**Overruled / changed.**

- **Frontend-first.** My first plan put the contract before any UI. That produces a contract
  describing the backend, which is the "loosely aligned" band of the rubric, not the top band.
- **`incident-response/` → `on-call-engineer/`.** Part 4 names the directory and its poller; the
  Module 4 deliverable names its inner files. Kept both: `on-call-engineer/` holds the poller and
  the module's file names inside it.
- **Kept Grafana Cloud.** Part 4 self-hosts, but explicitly says to skip that step when you use a
  managed OTel backend. Self-hosting is the fallback if the free tier becomes a distraction.
- **Did not adopt `_docs/tasks.md` as canonical.** It exists only to seed the tracker; the backlog
  mirror plus GitHub Issues is enough, and two live backlogs is how one of them goes stale.

**Known gaps.** Same as session 1, plus: the two skills are written but untested. Their first real
use will show whether they are specific enough for an agent to follow without correction.

## Session 4 — 2026-10-27: agent-agnostic cleanup

**What I asked for.** Remove the vendor-specific entry point and symlinks, and leave the repo
usable by any coding agent.

**What AI did.**

- Deleted the vendor-specific instruction file and the symlink tree that pointed into `.agents/`.
- Repointed every document at `AGENTS.md` and `.agents/` as the only agent entry point and the
  only place role and skill definitions live.
- Stated the tool-neutral contract in `AGENTS.md`, the README and `_docs/process.md`.
- Audited `_docs/handoff.md` against the repo: refreshed the git-log pointer, corrected the task
  count from 27 to 37, and replaced the stale T0.4 next step with the live T1.1 → T1.2 order.

**Verified myself.**

- A repo-wide search for the vendor name returns no file content or path.
- `.agents/agents/*.md` and `.agents/skills/*/SKILL.md` are still present and readable as plain
  Markdown.
- Every documented path still resolves: `AGENTS.md`, `.agents/`, `_docs/`, `_docs/team/`.
- The handoff's status and next-action claims agree with the README, the backlog and `git log`.

**Overruled / changed.**

- **Keeping a vendor symlink.** The symlinks existed only for one tool's discovery; the
  definitions themselves were already neutral, so the symlinks went with the entry-point file.
- **Renaming `.agents/`.** Left as-is: it is vendor-neutral, and `AGENTS.md` is the common entry
  point across agents.

**Known gaps.** None. No application code or contract file changed.

## Session 5 — 2026-10-27: concurrent agents and task breakdown

**What I asked for.** Make it explicit that multiple agents can run, and start breaking the plan
into tasks.

**What AI did.**

- Reconciled the loop's "one issue at a time" with §7: one issue per agent, several agents
  concurrently.
- Added parallel dispatch to the orchestrator lifecycle and a five-lane ceiling to §7.
- Added §2.1 to the plan: dependency-ordered lanes for all 37 backlog tasks, with the current P1
  dispatch target.

**Verified myself.**

- Every id in the plan's task map exists in `_docs/backlog.md`; the map introduces no new tasks.
- The lane order matches the phase exits and the D5–D6 parallel schedule.
- The P1 order matches the handoff's next action: T1.1 and T1.2 are issues #1 and #2.

**Overruled / changed.**

- **A second task list in the plan.** Task text stays in the backlog; the plan carries only ids,
  dependencies and lanes, so the repo still has one source of truth.
- **Unlimited parallelism.** Capped at five lanes because review, not build time, is the
  bottleneck.

**Known gaps.** None. No application code changed.

## Session 6 — 2026-10-27: T1.1 skeleton and T1.2 prototype

**What I asked for.** Go ahead with the two ready lanes: backend skeleton and mocked React prototype.

**What AI did.**

- Backend: `create_app`, cached pydantic settings, `/healthz` with a `db` field, `/api/version`, two
  TestClient tests, ruff config, and a Makefile with `install`, `run`, `test-unit`, `test-frontend`
  and `lint`.
- Frontend: three-screen Vite/React/Tailwind/TanStack prototype over one typed mock seam in
  `frontend/src/api/`, with seeded stock and orders, a movement ledger, per-line 409 handling and
  seven vitest tests.
- Added `.env.example` and moved both install caches inside the repo so the sandbox could run them.

**Verified myself.**

- `make lint` and `make test` pass: 2 backend tests, 7 frontend tests; `npm run build` succeeds.
- Playwright drove the short-line 409, cancel and fulfil flows and a 390px viewport; I reviewed the
  screenshots for layout and state.
- `make install` succeeds from the lockfiles; `make run` answers on `/healthz` and `/api/version`.

**Overruled / changed.**

- **The frontend subagent.** It produced no files after several minutes, so I stopped it and built
  the prototype directly rather than waiting.
- **Placeholder health shape.** Added `db: not_configured` instead of returning `status` alone,
  matching the issue while the database probe is deferred.
- **Full font packages.** Imported the latin subsets, cutting the CSS payload and asset list.

**Known gaps.** No contract, database, real API, CI or deploy yet; the prototype's data is the mock.
`make dev` is still T1.4.

## Session 7 — 2026-10-27: stock position chart

**What I asked for.** Add a graph to the Inventory screen.

**What AI did.**

- Added `StockChart`: per-SKU on-hand bars, reserved hatch, available-first ordering, low-stock
  outline and a shared scale.
- Wired it above the inventory list and added the legend/swatch styles.

**Verified myself.**

- `npm run lint`, `npm run build` and `npm test` pass; the Inventory screen test still covers the
  list and ledger.
- Loaded the running dev server, measured the rendered bar widths (SKU-4410's on-hand bar is 73px
  of 587px, fully reserved), and reviewed desktop and 390px screenshots.

**Overruled / changed.**

- **A chart library.** CSS bars add no dependency, match the existing gauge language and stay
  responsive.
- **A time-series chart.** The mock has no historical series yet; this chart uses current counters,
  and the ledger can feed history later.

**Known gaps.** The chart reads the mock; it has no historical trend or date range.

## Session 8 — 2026-10-27: front-end design system

**What I asked for.** Spin the front-end design into a durable artifact.

**What AI did.**

- Wrote `_docs/design-system.md`: palette, type, layout, component rules, states, responsive and
  accessibility contracts, motion, and the implementation map.
- Linked it from `AGENTS.md`, the README and the handoff.

**Verified myself.**

- Every token in the document matches `frontend/src/index.css`.
- Component rules were checked against the actual screens and the live dev server at 1440px and
  390px.
- The chart and ledger rules describe the components that are actually rendered.

**Overruled / changed.**

- **A new visual direction.** Kept the implemented stockroom/bin-ticket language; documenting it is
  what makes it reusable, and a redesign without a brief would be churn.
- **Screenshots in the document.** Left binaries out; the live prototype is the reference, and a
  stable screenshot set can arrive with the submission polish.

**Known gaps.** The document describes the mock prototype; P3 adds the generated client and may
extend the component set.

## Session 9 — 2026-10-27: focus and quantity hardening

**What I asked for.** Close the two frontend gaps before committing: modal focus behavior and loose
order quantities.

**What AI did.**

- Added `useModalFocus`: traps `Tab`, closes on `Escape`, restores focus to the trigger and restores
  body scrolling.
- Replaced the duplicated dialog/drawer effects with the hook.
- Blocked zero, negative and non-integer order quantities client-side, with an inline message,
  `aria-invalid` and a disabled submit.
- Added explicit Testing Library cleanup and regression tests for focus trap/restore and invalid
  quantities.

**Verified myself.**

- `npm test`: 9 frontend tests pass; `npm run lint` and `npm run typecheck` pass.
- The focus test asserts panel focus, `Shift+Tab` to the last control, `Tab` to the first, and focus
  restored to the trigger after `Escape`.
- The quantity test asserts the API is not called for a zero quantity.

**Overruled / changed.**

- **Duplicated modal effects.** One shared hook instead of two copies.
- **Server-only validation.** Kept the mock's `422` as defence in depth; the client now prevents the
  request.

**Known gaps.** The mock remains the data source; T1.3/T1.4 still own the contract and deploy.

## Session 10 — 2026-10-31: grooming all open issues and dispatching P1/P2

**What I asked for.** Spin the PM role over every open issue, then decide what to do about the
uncertain ones and start implementation.

**What AI did.**

- Split the 11 open issues across three PM subagents by write scope, with a fourth reconciling
  `_docs/backlog.md`. Every issue was read against `_docs/task-template.md` and `product-spec.md`.
- Added the missing `unit`/`integration`/`e2e` tags, bound every criterion to a spec AC id (or to
  §7 where the AC is API surface), and named the files and proof command for each issue.
- Filed #12 for the rollback AC that did not belong in #4 (a first deploy has no previous release).
- Resolved three contradictions: the spec has **23** ACs, not 24; the seed is **8** SKUs, not six;
  seeding proves I1–I3 with direct SQL instead of waiting on `/api/invariants`.
- Re-scoped #2 after reading the code: the mock and `mock.test.ts` prove the three problem shapes,
  but no toggle exists and the UI disables the controls that would surface `invalid_transition`/`422`.
  Visible error states moved to T3.3/T3.4; the rationale is recorded in the issue.
- Delegated the `/healthz` DB probe to #5 (it cannot exist before a database) instead of reopening
  the already-merged #1, and moved `compose.yaml` + `make dev` into #4 to match the P1 exit criteria.
- Committed the backlog mirror and dispatched engineers for #3, #5 and #7 in separate worktrees.
- Ran independent QA in fresh contexts per issue. The only defect was #5's `/healthz` 503 using
  `application/json` instead of the contract's `application/problem+json`; it was fixed and
  re-checked, and all three issues now have a PASS verdict.
- QA also exposed two Rule-6 gaps in the already-merged phase-1 work: `mock.test.ts` did not pin the
  `422`/`invalid_transition` types, and the version test stayed green with `commit` hardcoded. Added
  test-only PRs #17 (#2) and #18 (#1); both issues now have a PASS verdict as well.

**Verified myself.**

- Re-read every edited issue body after the edit; labels and the four template sections intact.
- Counted the ACs from `product-spec.md` §6 (US1 5 + US2 3 + US3 3 + US4 3 + US5 5 + US6 4 = 23)
  and the seeded catalogue from `_docs/domain.md` §6 (8 products); both differed from the issue text.
- Checked the `Makefile` before accepting any proof command: `migrate`, `seed`, `reset` and
  `test-integration` do not exist yet, so #5/#6 now own adding them rather than citing them.
- `make test`: 2 backend and 9 frontend tests pass; `make lint` had already passed on this commit.
- Confirmed Docker and Compose are available before telling #5 to provision its own test Postgres.
- Checked every PR diff against its file-ownership boundary before QA: #3 touched only
  `openapi.yaml` + `.spectral.yaml`, #5 only the DB/health/test/`Makefile` files after a docs edit
  was removed, #7 only `backend/domain/**` + new `tests/unit/**`.

**Overruled / changed.**

- **24 ACs → 23.** The count was a miscount in the backlog and #3; the spec needed no version bump.
- **Six SKUs → eight.** The issue was the only document that disagreed with the domain and backlog.
- **Rollback in T1.4 → #12.** A first deploy has nothing to roll back to; the rehearsal belongs in P5.
- **#2’s toggle ACs.** Re-scoped rather than implemented: building debug toggles into the throwaway
  prototype buys nothing once the contract is frozen, and Phase 3 owns visible error states.
- **#1 left closed-readiness alone.** Its issue text is satisfied; the spec’s DB probe moves to #5.
- **#4 queued behind #5.** Both edit `Makefile`; the file-ownership rule matters more than lane count.

**Known gaps.** #1 and #2 now have PASS verdicts and await merge/close; #18 and #17 add the missing
assertions. #4 cannot pass its deploy AC until a human provisions the then-planned managed platform and its token.
T3.1–T3.4 and T5.1–T5.3 have no issues yet by design. Open PRs: #13 docs, #15 (#3 contract),
#16 (#5 schema), #14 (#7 domain), #17/#18 (tests). All QA PASS; none merged — the human merge gate
is the remaining step.

## Session 11 — 2026-10-31: first merge gate and the #4 review

**What I asked for.** Merge the first batch, verify the merged tree, and start the next eligible lane.

**What AI did.**

- Fast-forwarded `main` to `763ad83`, removed the five clean worktrees and deleted the merged local
  branches. The `gh` branch-deletion warnings were expected: the worktrees held the branches.
- Found that #7 did not auto-close because PR #14's body omitted `Closes #7`; closed it after
  confirming the merge and the QA PASS.
- Dispatched #4 in a fresh worktree: CI, `compose.yaml` + `make dev`, a single-stage dev image, and a
  deploy job gated on a platform token with the skip-when-absent path. PR #19 uses `Refs #4`, not
  `Closes`, because the public-URL smoke can only happen after merge and provisioning.
- Ran QA #4 on the provable scope. The deploy AC is explicitly pending, not silently passed.

**Verified myself.**

- `make install`, `make lint`, `make test` (57 backend unit, 10 frontend) and `make test-integration`
  (15) all pass on `763ad83`, after the schema/domain/contract merges.
- `gh issue list`: #1, #2, #3, #5 and #7 closed; #4, #6 and #8–#12 open.
- QA #4's compose smoke reached `200 {"status":"ok","db":"ok"}`, the six tables and
  `alembic_version = 0001_schema_constraints`, then cleaned up its containers. Its PR CI run
  41177592538 is green, with both deploy jobs skipped on the PR as designed.
- #19's diff is limited to the workflow, Docker files, compose, the platform config and the `dev` Makefile
  target; `migrate`/`test-integration` and all product code are untouched.

**Overruled / changed.**

- **#4 stays open after merge.** Its deploy AC is post-merge by nature; `Refs #4` keeps the issue
  from closing on an unverified URL.
- **#6 queued behind #4.** Both edit `Makefile`; file ownership still beats lane count.
- **#7 closed by hand.** The PR should have carried `Closes #7`; the omission is recorded rather
  than hidden.

**Known gaps.** The managed app, its token and `STOCKROOM_DATABASE_URL` were human provisioning;
until then the deploy path and the public URL are unproven. #6 follows #4, and #8–#11 follow #6.
T3.1–T3.4 and T5.1–T5.3 remain unfiled by design.

## Session 12 — 2026-10-31: QA closes after the merge

**What I asked for.** Make QA the role that closes an issue after its PR is merged, instead of the
merge event or the orchestrator doing it.

**What AI did.**

- Added `AGENTS.md` rule 10: an issue closes only after its PR is merged and QA has re-checked
  `main`; PRs use `Refs #N`, not `Closes #N`.
- Updated `_docs/process.md`: the QA role owns the post-merge check and close, the permissions
  table grants it, §5 defines the post-merge verdict, §6 hands the close to QA, and the evidence
  chain now ends in a post-merge re-check and a closed issue.
- Updated both QA definitions and both engineer definitions, plus `_docs/handoff.md`, so no role
  document still says the orchestrator closes or that QA closes nothing.

**Verified myself.**

- Grepped the role docs and `AGENTS.md` for `Closes`, “close the issue” and “orchestrator closes”;
  no contradictory instruction remains.
- Confirmed #19 and #21 already use `Refs`, and that #7's manual close was the case this rule fixes.
- docs-only diff; `make lint` and `make test` are unaffected.

**Overruled / changed.**

- **Auto-close on merge.** `Closes` made the merge event close the issue before QA could re-check
  `main`; the convention is now `Refs`, with QA as the closer.
- **#4 stays open after merge.** Its deploy AC is a post-merge check, which is exactly the case
  this rule protects.

**Known gaps.** Existing merged PRs used `Closes`; no retroactive change. Post-merge closure only
happens if the orchestrator schedules the QA re-check after the human merge.

## Session 13 — 2026-10-31: authorized merges and the post-merge close

**What I asked for.** Allow the agent to finish QA → merge → close without weakening the
production gates.

**What AI did.**

- Narrowed `AGENTS.md` rule 8 instead of deleting it: agents still never deploy to production,
  rotate secrets or run SQL there; an agent may merge only after QA PASS and an explicit human
  authorization.
- Merged #19 (T1.4), then retargeted #21 (T2.2) to `main`. The stacked branch still carried the
  pre-squash #4 commits, so only the #6 commits were replayed onto `main`.
- Ran `make lint`, `make test` and `make test-integration` on the rebased #6 branch, then merged #21.
- Dispatched a fresh QA post-merge check on `main` at `59ba86f`; it posted
  `## QA: post-merge PASS` and closed #6.
- Updated the process, role table and handoff docs so the human reviewer authorizes merges and the
  orchestrator executes them.

**Verified myself.**

- `main` at `59ba86f`: 57 backend unit, 10 frontend and 20 integration tests pass; lint clean.
- CI on PR #21 after the rebase: lint/tests/contract and container build green; deploy jobs skipped.
- #6's post-merge QA re-ran the seed twice (8 → 0 new movements) on a disposable DB and an isolated
  compose project, then closed the issue.
- #4 stayed open: its deploy AC was still pending managed-platform provisioning and the public-URL smoke.

**Overruled / changed.**

- **Rule 8 was narrowed, not deleted.** Production deploys, secret rotation and prod SQL remain
  human-only; only the merge prohibition changed.
- **#21 needed a replay, not a retarget alone.** After the #19 squash, the stacked branch still had
  the pre-squash commits; `git rebase --onto origin/main 2bb2ccb` kept only the #6 commits.
- **#6 closed by QA, not by the merge.** This is the first issue to use the rule from session 12.

**Known gaps.** #4's dev deploy and public URL were unproven until the managed platform and Postgres were
provisioned; both were later removed in favour of self-hosting. #8–#11 were next, based on `main`.

## Session 14 — 2026-11-01: issue #8, reservation transaction and POST /api/orders

**What I asked for.** Spin the SE and implement issue #8 (T2.4): atomic reservation via `POST
/api/orders`, with the per-line 409 rejection, all-or-nothing transaction, ordered `FOR UPDATE`
locking, and the unit + integration tests that prove US1-AC1..5, US2-AC3, I5 and I6.

**What AI did.**

- `backend/domain/reservation.py`: pure `validate_availability` + `InsufficientStock`/`ShortLine`
  domain types (ordered lock validation, every short line named).
- `backend/domain/movements.py`: `reserve_movements` accepts an optional `note`.
- `backend/domain/__init__.py`: export the new reservation symbols.
- `backend/api/problems.py`: shared RFC 9457 `problem`/`validation_error` helper carrying `trace_id`.
- `backend/api/orders.py`: `POST /api/orders` — locks touched stock rows ascending SKU with
  `FOR UPDATE`, validates all lines, inserts order/lines/movements, updates cached counters in one
  transaction; maps `InsufficientStock` → `409 insufficient_stock` with `errors[]`, unknown SKU /
  bad qty → `422 validation_error`.
- `backend/main.py`: register the orders router and a 500 `problem+json` error handler.
- `tests/unit/test_domain_reservation.py`: unit coverage for `validate_availability`.
- `tests/integration/test_orders.py`: 5 tests including the `-k reserve` proof (US1-AC1 short line
  rejects whole order, US1-AC2 successful order reserves every line, US1-AC5 unknown SKU is a 422),
  plus US1-AC4 invalid quantity and duplicate-line aggregation.
- `_docs/ai-usage-report.md`: this entry.

**Verified myself.**

- `make lint` backend: ruff check and ruff format clean (35 files).
- `make test-unit`: 30 unit tests pass (27 pre-existing + 3 new reservation).
- `make test-integration`: 25 integration tests pass (20 pre-existing + 5 new orders).
- `make test-integration -k reserve` → 5 passed, which proves the issue's three AC tests
  (US1-AC1, US1-AC2, US1-AC5) plus the extra coverage.
- No PII or secrets added; errors are `application/problem+json` with `trace_id`; domain stays
  pure (no SQLAlchemy/FastAPI imports), enforced by the existing `test_domain_purity`.

**Overruled / changed.**

- `/api/invariants` is not part of issue #8 (it lands in T2.5/#10), so the successful-order test
  verifies I5/I6 with direct SQL against the ledger instead of calling the not-yet-existing
  endpoint.
- A `session.flush()` after inserting the order row was required because SQLAlchemy autoflush
  would otherwise insert `movements` (FK to `orders`) before the order row exists.

**Known gaps.** `/api/invariants`, `GET /api/orders`, cancel and fulfil endpoints (issues #10,
#11) are not part of this issue. The frontend is still mock-backed; T3.3 wires the real client.

## Session 15 — 2026-11-01: QA owns the merge and the close

**What I asked for.** Stop pausing at a human merge gate: when QA passes an issue, QA should merge
the branch to `main` and close the issue. When an engineer starts an issue, it must pull the
current `main` from GitHub first. Update every part of the process that encoded the old rule.

**What AI did.**

- `AGENTS.md`: rules 8 and 10 now make QA the only merger — after `PASS` and green CI it
  squash-merges, re-checks `main` at the merge commit, and closes only if that passes. Production
  deploys and prod SQL stay human-only. The task steps now require `git fetch origin` and a branch
  from `origin/main`, and the definition of done records the post-merge verdict.
- `_docs/process.md`: role table and permissions grant QA the merge; the loop diagram and prose
  show QA merging, deploying dev and closing after the post-merge proof; §5 documents the merge
  mechanics; the orchestrator lifecycle requires freshly fetched `origin/main`, never merges, and
  rebases remaining lanes after each merge; §7–§9 and §11–§12 use the QA gate.
- `_docs/team/qa-engineer.md`, `_docs/team/software-engineer.md`, `.agents/agents/qa-engineer.md`
  and `.agents/agents/software-engineer.md`: QA has a "Merging after PASS" procedure; the engineer
  starts from `origin/main` and never merges or closes.
- `_docs/handoff.md` and `_docs/plan.md`: the human no longer authorizes each merge; the serial
  QA merge is the bottleneck.
- `_docs/backlog.md`: T2.4 (#8) marked merged; T2.5–T2.7 (#9–#11) are next.

**Verified myself.**

- Grepped `AGENTS.md`, `README.md`, the process and role docs, `.agents/` and `plan.md` for
  `human merge`, `authorize`, `human reviewer` and `orchestrator merges`; the only remaining hits
  are historical entries in this report. The on-call "never merge" rule stays, because only QA
  merges.
- Pushed the process change as `a33a96d`; `git diff --check` clean.
- QA resumed in a fresh-enough context, rebased `feat/8-reservation-transaction` on `a33a96d`,
  committed only its integration tests, and re-ran the proof: 28 integration, 64 unit, ruff clean.
- PR #22 CI green (3 successful, 2 skipped deploy checks); squash merge `90f4a43`.
- Post-merge proof on a clean worktree at `origin/main` `90f4a43`: `make lint` clean, `make test`
  64 backend + 10 frontend, 28 integration passed; QA posted `## QA: post-merge PASS` and closed #8.

**Overruled / changed.**

- **The human merge gate is gone.** The orchestrator no longer executes merges on a human
  instruction; QA merges after its own PASS and green CI. Production promotion remains a human
  gate, so rule 8's production prohibitions are untouched.
- **QA is now judge and merger.** The separation that matters is still engineer vs QA; the merge
  is mechanical, allowed only after a posted `PASS`, green CI and a rebased proof, and the
  post-merge check runs independently on `main`.
- **A stale base is a process defect.** Engineers and QA both fetch `origin/main` before work or
  merge; the orchestrator rebases waiting lanes after every merge.

**Known gaps.** #8 leaves two non-AC follow-ups: order/movement ids are UUIDv4 while `openapi.yaml`
and `product-spec.md` describe UUIDv7, and a malformed JSON body becomes a 500 instead of a 422.
Worktrees for #9 and #10 exist and are based on `90f4a43`, so they satisfy the new freshness rule.

## Session 16 — 2026-11-01: issue #9, stock endpoints and the invariant report

**What I asked for.** Another agent had started issue #9 (T2.5) but left no usable handoff: two
untracked files (`backend/api/stock.py`, `backend/api/invariants.py`) that did not import or run,
no tests, no product endpoint, no router registration and no session record. Finish the issue and
leave the handoff artifacts the process requires.

**What AI did.**

- Rebased `feat/9-stock-endpoints` on current `origin/main` (`148005d`) before touching the work.
- Rewrote `backend/api/stock.py`: `GET /api/stock`, `POST /api/stock/receive`,
  `POST /api/stock/adjust`, `GET /api/stock/{sku}/movements` and `GET /api/invariants`. Every stock
  write is one transaction that locks the affected row `FOR UPDATE` in ascending SKU order,
  validates under the lock, inserts exactly one movement and updates the cached counter.
- Added `backend/api/products.py` for `GET /api/products`, including the derived `available` and
  `low` fields from `product-spec.md` §7 / US6-AC1.
- Registered the products and stock routers in `backend/main.py`.
- Deleted the partial `backend/api/invariants.py`; the invariant route lives in `stock.py` because
  that is the file the issue's Constraints name for T2.5.
- Added `tests/integration/test_stock.py` with 27 tests covering US5-AC1..AC5 and US6-AC1..AC3,
  including the route-table plus `openapi.yaml` proof that movements have no mutation path.
- Opened PR #23 with `Refs #9`; CI (lint, tests and contract; container build) is green.

**Verified myself.**

- Red first: the new suite failed before the routers existed and passed after (27/27).
- `make lint`: ruff check and ruff format clean across backend and tests; tsc and eslint clean.
- `make test`: 64 backend unit + 10 frontend tests pass.
- `make test-integration`: 55 passed, including the 27 new stock tests.
- Read the behaviour back: receive writes one `receive` movement with actor and note; adjust
  rejects `negative_on_hand` before `would_breach_reserved` and writes nothing on either; movements
  are newest first with a running `on_hand_after` and the order reference; a deliberately corrupted
  `stock.on_hand` returns `200` with an I2 violation rather than `500`.

**Overruled / changed.**

- **The leftover implementation was discarded.** It indexed a plain `dict` as `input.sku`, imported
  a non-existent `adjust_movements`, never registered the routers, and returned `name: null` for a
  required `StockRow` field. Keeping it would have required rewriting every handler anyway.
- **Negative check first.** US5-AC3 must win when an adjustment both goes below zero and below
  `reserved`; checking the reservation first would label every seeded-SKU negative adjustment
  `would_breach_reserved`, because `reserved` is zero.
- **Receive note is optional and stored as null when absent**, matching `ReceiveRequest`; adjust
  still requires a non-empty note (US5-AC4).
- **No domain changes.** The stock movement rows are built in the API layer from the existing
  `MovementReason`; `backend/domain/` stays as merged in #7.

**Known gaps.** No QA verdict or merge yet: #9 is in review as PR #23 and is left open for QA.
`GET /api/products` is part of `openapi.yaml` but the frontend still reads the mock; T3.3 wires the
real client. A malformed JSON
body still reaches the global 500 handler, the same pre-existing gap noted after #8 — not part of
this issue's ACs.

## Session 17 — 2026-11-01: independent QA, merge and close for #9

**What I asked for.** Spin a fresh QA session to verify issue #9 against its acceptance criteria,
then let QA merge and close it under the process from session 15.

**What AI did.**

- Created an isolated worktree from `origin/feat/9-stock-endpoints` (PR #23 head `39de9d5`); the
  engineer's comment and PR body were treated as claims, not evidence.
- Checked every AC against the running code: receive writes one movement and moves the counters;
  adjust rejects `would_breach_reserved` and `negative_on_hand` with no write; note validation is
  `422`; the route table and `openapi.yaml` expose only `GET` on the movements path; the product
  list derives `available` and `low`; movements are newest first with a running balance; the
  invariant report returns `200` on healthy, corrupted-cache, broken-ledger and broken-order data.
- Added `tests/integration/test_stock_qa.py` with 19 tests and left the engineer's
  `test_stock.py` intact; nine independent product-line reverts were each observed to fail the
  focused test, then restored.
- Committed only the QA test file, rebased on `origin/main`, re-ran the proof, pushed the test
  commit to the PR branch, waited for green CI, and squash-merged PR #23 as `cfb50fa`.
- Re-ran the proof in a clean worktree at `origin/main` `cfb50fa`, posted `## QA: PASS` and
  `## QA: post-merge PASS`, and closed #9.

**Verified myself.**

- Pre-merge: 74 integration (49 stock), 64 unit, 10 frontend; ruff, tsc and eslint clean; CI green
  (3 successful, 2 skipped deploy checks).
- Post-merge at `cfb50fa`: `make lint` clean, `make test` 64 unit + 10 frontend, 74 integration.
- `gh pr view 23` MERGED at `cfb50fa`; `gh issue view 9` CLOSED; `origin/main` at `cfb50fa`.
- QA modified no product code; `git diff origin/main -- backend openapi.yaml frontend` was empty.

**Overruled / changed.**

- **A 405 is not a problem document.** `PUT`/`PATCH`/`DELETE` on the movements path return
  `405 application/json` without `trace_id`. US5-AC5 still passes (no mutation path exists), but
  the body diverges from the `default` problem response in `openapi.yaml`. Follow-up, app-wide.
- **Green CI does not cover integration tests.** `ci.yml` runs lint, unit and the container build;
  the integration proof is local. This is the process gap that makes a green PR insufficient on
  its own.

**Known gaps.** The 405 problem shape and CI integration coverage are not fixed here; both are
follow-ups. T2.6 (#10) is next.

## Session 18 — 2026-11-03: order list, detail, cancel and fulfil (#10)

**What I asked for.** A software-engineer session to implement T2.6 exactly as groomed: cancel a
`confirmed` order and release its stock, fulfil one and ship it, and expose the order list and
detail from `product-spec.md` §7 — with every transition leaving the ledger balanced.

**What AI did.**

- Wrote the nine failing integration tests first, appended to `tests/integration/test_orders.py`;
  #8's tests were left untouched. They cover US3-AC1..AC3, US4-AC1/AC3, the status-filtered list
  (including the unknown-status `422`), the detail with snapshotted prices and the timeline, the
  `404` problem for a missing id on all three routes, and a two-client concurrent double cancel.
- Added `GET /api/orders`, `GET /api/orders/{id}`, `POST /api/orders/{id}/cancel` and
  `POST /api/orders/{id}/fulfil` to `backend/api/orders.py`.
- Cancel and fulfil are one transaction each: lock the order row with `FOR UPDATE` (the lifecycle
  serialisation point), load the lines, lock every touched stock row in ascending SKU order,
  validate the move with the #7 `transition` predicate, write one `release` or `ship` row per line
  through the existing `release_movements` / `ship_movements` factories, update both cached
  counters and commit. A forbidden move raises before any write, so the rollback writes nothing.
- Built the `Order` document from `openapi.yaml`: `id`, `customer_ref`, `status`, `created_at`,
  lines with the line's snapshotted `unit_price_cents` and the product name, and movements newest
  first. `on_hand_after` is a window over every movement for the same SKU, so it means the same
  thing as in the stock audit trail, not a balance accumulated from this order alone.
- Unknown order status is a `422 validation_error`; a missing order is a `404 not_found`; an
  illegal transition is a `409 invalid_transition`; all three are `application/problem+json` with
  a `trace_id` from `backend/api/problems.py`. No PII or secret is logged.

**Verified myself.**

- Red first: the nine new tests failed (`9 failed, 10 passed`) before the implementation.
- `make lint` clean (ruff check, ruff format, tsc, eslint).
- `make test`: 64 unit, 10 frontend.
- `make test-integration`: 83 passed (74 before this branch, 9 new).
- `uv run pytest tests/integration -k orders`: 19 passed, including every `integration` case in
  the issue.
- The concurrent-cancel test starts two requests on the same order and asserts one `200`, one
  `409`, exactly one release row per line and the counters back at `reserved = 0`; it exercises the
  order-row lock rather than only the sequential path.

**Overruled / changed.**

- **Malformed order ids are `404`, not `422`.** The path parameter stays a string and is parsed to
  a UUID by hand, because `openapi.yaml` lists only `404` (or `404`/`409`) for these routes. A
  FastAPI-typed UUID field would have produced a `422` body the contract does not describe.
- **No `openapi.yaml` change.** The existing contract already described all four routes and the
  `Order`, `OrderLine`, `Movement` and `OrderStatus` shapes; the implementation matches it, so the
  generated client is untouched.
- **Concurrency proved with two TestClient portals**, not a live `uvicorn` server: the ordering
  guarantee under test is the database row lock, and both requests still reach PostgreSQL in
  parallel, which keeps the engineer file independent of QA's live-server harness.

**Known gaps.** `GET /api/orders` has no pagination, matching the contract, and builds each row
with its full timeline (a few reads per order) — fine for the seeded demo, a follow-up if the
list grows. The app-wide 405 and malformed-JSON problem-shape gaps noted after #8 and #9 remain.
All seven acceptance criteria are covered; #10 is left open for QA (no merge, no close, no deploy).

## Session 19 — 2026-11-03: independent QA, merge and close for #10

**What I asked for.** Spin a fresh QA session for issue #10, verify it against the acceptance
criteria, and let QA merge and close it under the policy from session 15.

**What AI did.**

- Created an isolated worktree from `origin/feat/10-order-endpoints` (PR #25 head `81e6a10`); the
  implementer's comment and PR body were treated as claims, not evidence.
- Checked all seven ACs against the running code: cancel releases one movement per line and leaves
  `on_hand` alone; double-cancel and cancel-after-fulfil are `409 invalid_transition` with no
  write; fulfil ships both counters down by `q`; the status-filtered list carries the required
  fields and rejects an unknown status with `422`; detail returns snapshotted prices, reservations
  and the movement timeline, and a missing id is a `404` problem.
- Added `tests/integration/test_orders_lifecycle_qa.py` with 6 tests and left both existing order
  test files intact; five independent product-line reverts were observed failing and restored.
- Committed only the QA test file (`aad767d`), rebased on `origin/main`, re-ran the proof, pushed
  the test commit to the PR branch, waited for green CI, and squash-merged PR #25 as `4069ab6`.
- Re-ran the proof in a clean worktree at `origin/main` `4069ab6`, posted `## QA: PASS` and
  `## QA: post-merge PASS`, and closed #10.

**Verified myself.**

- Pre-merge: 89 integration (25 orders), 64 unit, 10 frontend; ruff, tsc and eslint clean; CI green
  (3 successful, 2 skipped deploy checks).
- Post-merge at `4069ab6`: `make lint` clean, `make test` 64 unit + 10 frontend, 89 integration.
- `gh pr view 25` MERGED at `4069ab6`; `gh issue view 10` CLOSED; `origin/main` advanced.
- QA modified no product code; the only QA change is the added test file.

**Overruled / changed.**

- **No product defect found.** The implementation's transition locking, ledger rows and counters
  matched the criteria on the first independent pass.
- **The pre-existing problem-shape gaps remain.** The 405 bodies are not `problem+json`, a
  malformed JSON body still reaches the global 500 handler, and CI still does not run integration
  tests. None of these are #10 AC failures; they are follow-ups.

**Known gaps.** T2.7 (#11) is the last backend-core task. The #8/#9/#10 follow-ups (UUIDv7 vs v4,
405 problem shape, malformed JSON, CI integration coverage) remain unfiled.

## Session 20 — 2026-11-03: problem+json error model with trace ids (#11)

**What I asked for.** A software-engineer session to implement T2.7 exactly as groomed: make
every API error machine-readable problem+json, give one request one stable `trace_id`, and prove
that no stack trace, SQL, connection string or customer PII reaches a response body or an error
log.

**What AI did.**

- Wrote `tests/integration/test_errors.py` first (13 tests): unknown route and wrong method,
  unknown SKU on order creation, malformed JSON, framework validation with field path/value,
  missing order, invalid transition, the short-line `errors[]` shape, a forced 500, trace-id
  scope and uniqueness, and secret/PII non-leak assertions for both the response and the log.
  A probe app built by `create_app()` supplies the Pydantic body and the raising route that no
  production endpoint declares, so the actual handlers are exercised.
- Replaced the fresh-UUID-per-call in `backend/api/problems.py` with a request-scoped
  `ContextVar`: the middleware sets one id, `problem()` and `validation_error()` reuse it, and
  the fallback still works outside a request. `validation_error()` now accepts `errors[]`.
- Added `backend/api/errors.py`: HTTP middleware for the trace id, a Starlette `HTTPException`
  handler (404/405, preserving `Allow`), a `RequestValidationError` handler that emits
  `field`/`message`/`value` entries and never echoes structured or secret-bearing input, a
  `JSONDecodeError`/`UnicodeDecodeError` handler that turns malformed JSON into a 422, and an
  opaque catch-all that logs only the exception class plus the trace id.
- Registered all of it through `register_error_handlers()` in `backend/main.py`.
- Caught the catch-all inside the middleware as well as registering it on the app: Starlette's
  `ServerErrorMiddleware` re-raises after answering, which would let uvicorn print the traceback.
  The middleware contains the failure, so the only error log is the safe one.
- Extended `openapi.yaml` with a `ValidationProblemError` schema, a `Problem.errors` `oneOf`,
  and an explicit `ValidationProblem.errors` reference; documented `method_not_allowed`,
  `unexpected` and the generic `http_error` fallback categories.
- Removed `exc_info=True` from the health-probe warning in `backend/db/session.py`. It printed a
  driver traceback and could carry connection details; AC5 says _any_ error log, so this was the
  one minimal change outside the issue's named files.

**Verified myself.**

- Red first: `tests/integration/test_errors.py` failed 8 of 13 before the handlers existed
  (missing `current_trace_id`, `application/json` for 404/405/validation, malformed JSON raising
  through the global handler, and no safe 500 log). The health-log assertion was also observed
  failing against the old `exc_info=True` line, then restored.
- `make lint` clean (ruff check, ruff format, tsc, eslint).
- `make test`: 64 unit, 10 frontend.
- `make test-integration`: 102 passed (89 before this branch, 13 new).
- `uv run pytest tests/integration -k errors`: 13 passed.
- `npx --yes @stoplight/spectral-cli lint openapi.yaml`: no errors.

**Overruled / changed.**

- **The contract changed.** Validation errors need a field-level entry shape that cannot
  masquerade as `ProblemError` (which requires `sku`/`requested`/`available`/`short_by`), so
  `ValidationProblemError` was added and `Problem.errors` widened to `oneOf`. The repo has no
  generated frontend client yet (T3.1 owns it), and `frontend/src/api/types.ts` is the hand-written
  mock; it still types `errors` as `ProblemError[]`. That is recorded as a gap rather than edited
  here, because widening it would force unrelated screen changes.
- **One file outside the stated ownership changed.** `backend/db/session.py` lost `exc_info=True`
  so the health-probe warning stops printing a traceback. AC5 says "any error log", and the
  alternative was to ship a known leak. No product behaviour changed.
- **The catch-all is caught in middleware.** Registering `Exception` alone satisfies FastAPI but
  still lets Starlette re-raise and uvicorn log the stack trace. Containing it in the middleware
  is what makes the "safe log only" claim true in a real server; the registered handler remains as
  a fallback.
- **Health's 503 is untouched.** `backend/api/health.py` still mints its own trace id, so its body
  id differs from the request id. The acceptance criteria enumerate 404/409/422/500, not 503, and
  the file was outside this issue's ownership; this is the one remaining inconsistency.

**Known gaps.** `GET /healthz` 503 does not use the request-scoped id (above). The frontend mock
still models only `ProblemError[]`. Correlating the trace id with logs, traces and the trace UI is
T6.1–T6.3, explicitly out of scope. CI still does not run integration tests (pre-existing). #11 is
left open for QA: no merge, no close, no deploy.

## Session 21 — 2026-11-03: independent QA, merge and close for #11

**What I asked for.** Spin a fresh QA session for issue #11, verify it against the acceptance
criteria, and let QA merge and close it under the policy from session 15.

**What AI did.**

- Created an isolated worktree from `origin/feat/11-error-model` (PR #26 head), treating the
  implementer's comment and PR body as claims rather than evidence.
- Checked every AC against the running code: 404/405/409/422/500 (forced) are problem+json with all
  five fields and a non-empty trace id; validation `errors[]` carries the dotted field path and
  offending scalar while omitting secret values; an unknown SKU is a 422 naming the SKU; two errors
  in one request share the middleware/`ContextVar` id while separate requests differ; forced-500
  and health-probe logs contain no traceback, SQL, DSN or PII.
- Confirmed the changed error contract: `ValidationProblemError` and the `Problem.errors` `oneOf`
  match the emitted documents; the `409 insufficient_stock` per-line shape is preserved; spectral
  reports no errors.
- Added `tests/integration/test_errors_qa.py` with 18 tests, leaving the engineer's
  `test_errors.py` intact; four independent product-line reverts were observed failing and
  restored.
- Committed only the QA test file (`a73fd5d`), rebased on `origin/main`, re-ran the proof, pushed
  it to the PR branch, waited for green CI, and squash-merged PR #26 as `a95bef8`.
- The session dropped immediately after the merge. Resumed it to run the post-merge proof on a
  clean worktree at `origin/main` `a95bef8`, post `## QA: post-merge PASS`, and close #11.

**Verified myself.**

- Pre-merge: 120 integration (31 error tests), 64 unit, 10 frontend; ruff, tsc, eslint and spectral
  clean; CI green (3 successful, 2 skipped deploy checks).
- Post-merge at `a95bef8`: `make lint` clean, `make test` 64 unit + 10 frontend, 120 integration.
  The first post-merge integration attempt hit a stopped Docker/OrbStack daemon at the session
  fixture, not a test failure; after restarting it, all 120 passed.
- `gh pr view 26` MERGED at `a95bef8`; `gh issue view 11` CLOSED; QA modified no product code.

**Overruled / changed.**

- **The two earlier problem-shape gaps are fixed.** 405s are now problem+json, and malformed JSON
  is a 422 instead of a 500.
- **Two follow-ups are not #11 failures.** The `/healthz` 503 still mints its own trace id
  (outside the enumerated 404/409/422/500 set and the issue's file ownership), and the manual 422
  paths in orders/stock omit `errors[]` because they do not go through `RequestValidationError`.
- **CI still does not run integration tests**, so the 120-test proof remains local.

**Known gaps.** `/healthz` 503 trace-id scope, manual 422 field detail, the narrow frontend mock
`ProblemError[]` type, and CI integration coverage are unfiled follow-ups. Phase 2 is complete;
Phase 3 (frontend) is next.

## Session 22 — 2026-11-03: local/self-hosted only, managed platform removed

**What I asked for.** Remove the managed deployment platform from the project. The stack should run
locally or on a self-hosted Docker host, with no cloud provider dependency, and the old references
should be gone from every file.

**What AI did.**

- Deleted the managed-platform config file at the repo root.
- `.github/workflows/ci.yml`: removed the `deploy-token` and `deploy-dev` jobs and all platform
  comments. CI now runs lint, unit/frontend tests, the OpenAPI contract lint and the container
  build, and never deploys.
- `README.md`: database, CI/CD, deployment topology, status table and rubric rows now describe a
  local or self-hosted Docker Compose stack.
- `_docs/plan.md`: hosting assumption, P1/P3/P5 phase text, the D2/D6 schedule entries, the
  rubric rows and the Postgres risk now assume a self-hosted host.
- `_docs/handoff.md`: current status, the D2 decision, open item O3, the work loop and the next
  session text no longer require cloud provisioning.
- `_docs/backlog.md`: T1.4 is CI + local compose with no managed deploy; T5.3 tags the image and a
  human runs the same tag on the self-hosted host; the Phase 5 exit follows that.
- `_docs/process.md` and `AGENTS.md` rule 8: a merge runs CI and never deploys; deploying the
  built image to the self-hosted host is a human step, and production promotion stays human-only.
- Issue #4: rewrote its goal and acceptance criteria for CI + `make dev` + `docker compose up
--build`, removed the managed-platform ACs and constraints, and posted a scope-change comment.
- Rebased PR #24 (`readme-local-docker`) onto the new `main`, resolving the README conflict by
  keeping the cleaned README and folding in the PR's Docker workflow section; force-pushed.
- Dispatched QA for #4 under the rewritten local-stack ACs; it posted `## QA: PASS` and closed #4.
- Earlier report entries: neutralised the vendor name so the audit trail still records that a
  managed platform was planned and later removed, without leaving the name in the file.

**Verified myself.**

- A case-insensitive search for the provider name over the tracked tree has no operational
  references. The only remaining hits are a base64 integrity substring in
  `frontend/package-lock.json` (the `dom-accessibility-api` package, unrelated) and the
  `readme-local-docker` worktree checkout, which is not part of `main`.
- A filename search for the provider name confirms the root config is gone, including the
  `readme-local-docker` worktree after the rebase.
- `git diff --check` is clean; no product code, migrations, tests or `openapi.yaml` changed.
- CI run `41623402833` on the pushed commit passed with only the `test` and `container build`
  jobs; there is no deploy job.
- PR #24 head `a0fe533` is based on `ad55fca`; CI run `41640252860` is green (test, container build
  and GitGuardian), and the PR was squash-merged at `f13b6e8`.
- #4 is closed after QA re-checked the rewritten local-stack criteria and posted
  `## QA: PASS` at https://github.com/cancinoray/stockroom/issues/4#issuecomment-6605735055.

**Overruled / changed.**

- **No automatic deployment on merge.** QA's merge runs CI only. A human runs the built image on
  the self-hosted host.
- **Self-hosting is optional for the build.** Local `docker compose` is the default; a host is
  only needed for a public demo in P5.
- **The audit trail keeps the decision.** Earlier entries were edited only to remove the vendor
  name; they still say a managed platform was planned and later dropped.

**Known gaps.** No red CI run exists on the new workflow — QA proved red-on-failure locally by
injecting a lint error and a failing test. P5 still owes the deployment and release docs for the
self-hosted host.

## Session 25 — 2026-11-04: contract alignment and the T3.1 merge

**What I asked for.** Go ahead with the recommendation after T3.1's contract check exposed drift:
fix the backend contract first, then rebase and finish T3.1.

**What AI did.**

- Filed #32 (T2.8) for the 70 structural differences the #27 check found: `{order_id}` vs `{id}`,
  undeclared 201s, missing request/response models and problem components, and the `Health`/
  `Version` names.
- Dispatched a backend engineer: added `backend/api/schemas.py` and `backend/api/openapi.py`,
  `response_model`/`responses`/`status_code=` declarations, `Path(alias="id")` and the contract
  component names. The check went from **70 differences to 0**; `make test-integration` was 120
  passed; the red path was demonstrated by renaming `StockRow.low`.
- Dispatched QA for #32: verified the check, request/response models, problem responses, 201s and
  runtime compatibility; added `tests/unit/test_openapi_contract_qa.py`; merged PR #33 as
  `d620514` and closed #32.
- Resumed the T3.1 engineer: rebased `feat/27-generated-client` onto `d620514`, resolved only the
  report conflict (Session 23 before Session 24), re-ran the proof and force-pushed; `check:contract`
  is 0 and CI is green.
- Dispatched QA for #27: verified all 13 ACs, found AC11 (the real default `api` export) uncovered
  and added `frontend/src/api/index.test.ts`, merged PR #31 as `83445b2` and closed #27.

**Verified myself.**

- `check:contract` exits 0 on `main`; both `main` merges are green in CI.
- Pre- and post-merge proofs: 120 integration, 74 backend unit, 40 frontend, lint clean.
- QA's revert checks covered the 201 declarations, `{id}` paths, a response field, a problem
  response, the normalizer, hook invalidation, the default export and a contract field rename.
- `gh issue view 32` and `gh issue view 27` are CLOSED; `main` is `83445b2`.

**Overruled / changed.**

- **The contract is frozen; the code moved to it.** No `openapi.yaml` change was needed.
- **The backend was the right place to fix the drift.** A baseline/allowlist was rejected; the
  check is strict from day one.
- **QA caught a hollow AC.** The default-export claim passed all existing tests until QA added a
  test that fails when the mock export is restored.
- **OpenAPI version text remains different** (`3.1.0` generated vs `3.0.3` in the contract). The
  check compares structure only; noted as a documentation follow-up.

**Known gaps.** T3.2 (#28), T3.3 (#29) and T3.4 (#30) are next and can run in parallel now that the
API seam is merged. The screens still use the mock until they consume the new hooks.

## Session 23 — 2026-11-04: generated client, hooks and the contract check (#27)

**What I asked for.** Implement T3.1 exactly: generate types from `openapi.yaml`, one typed
`openapi-fetch` client, hand-built query hooks over the §7 surface, one never-throwing
`problem+json` normalizer, and a CI check that stops FastAPI's document and the contract from
drifting. Work in a worktree from `origin/main`, open a PR with `Refs #27`, and do not merge or
close.

**What AI did.**

- Added `openapi-typescript` (dev) and `openapi-fetch` (runtime). `npm run generate:api`
  regenerates `frontend/src/api/schema.d.ts`; the generated file is committed and a second run is
  byte-identical.
- Replaced every hand-written §7 response interface in `frontend/src/api/types.ts` with aliases of
  `components['schemas']`. `StockroomApi` remains the hand-built behaviour surface and now also
  covers products, order detail and invariants.
- Added `frontend/src/api/problem.ts`: preserves `type`, `title`, `status`, `detail`, `trace_id`
  and `errors[]`; uses `in`-operator guards for `ProblemError` vs `ValidationProblemError`; turns
  non-JSON bodies, network failures and 5xx-without-body into a generic `unexpected` problem and
  never throws.
- Added `frontend/src/api/client.ts`: `openapi-fetch<paths>` with a same-origin `/api` default and
  `VITE_API_BASE_URL` override; every call funnels through one `request` helper that throws
  `ApiProblem`. `index.ts` now exports the real `api`; `createMockApi` stays exported.
- Added hooks for products, stock, movements, orders (optional status), order detail, create,
  cancel, fulfil and invariants with stable keys and the invalidation rules from the issue. No
  optimistic counter writes; `setQueryData` is asserted never called.
- Extended the mock with `listProducts`, `getOrder` and `listInvariants` so the existing screen
  tests keep injecting it unchanged.
- Added `frontend/scripts/check-contract.mjs` and wired it into `.github/workflows/ci.yml`.
- Red first: the 9 new tests failed before the modules existed (missing `./problem`, `./client`,
  `queryKeys.order`, `useProducts`, `useInvariants`).
- Opened PR #31 with `Refs #27`. No merge, no close.

**Verified myself.**

- `cd frontend && npm run generate:api && git --no-pager diff --exit-code -- src/api/schema.d.ts`:
  clean (`GENERATED_SCHEMA_CLEAN`).
- `npm test -- --run`: 38 passed, 1 skipped (a compile-time-only case); the existing Inventory and
  Place Order screen tests pass unchanged.
- `npm run typecheck` and `npm run lint`: clean. The `@ts-expect-error` call sites prove the
  generated client rejects a wrong path, verb and missing request body field.
- `make lint && make test`: ruff check/format, tsc and eslint clean; 64 backend unit + 38 frontend
  passed + 1 skipped.
- `rg "interface (StockRow|Order|Movement|Problem|Product)" frontend/src/api`: no matches.
- `npm run check:contract` on `origin/main` `7e6f49c`: exit 1 with 70 structural differences, not
  zero. Temporarily renamed `trace_id` to `traceId` in `openapi.yaml`; the check reported the
  renamed schema and exited 1; reverted, nothing committed.

**Overruled / changed.**

- **The contract check exposed pre-existing drift, so AC9/AC10 were blocked at first submission.**
  FastAPI emits `/api/orders/{order_id}` vs the contract's `{id}`; receive/adjust/create declare `200` vs `201`;
  handlers return `JSONResponse`, so the generated document has no request bodies or §7 entity
  response schemas. Fixing that needs a PM-approved backend/contract issue; #27 forbids changing
  `openapi.yaml` or the backend here.
- **`ApiProblem` keeps a compatibility view.** Existing screens read `problem.errors` as short-line
  entries, so `ApiProblem.problem` is a derived `ProblemView`; the full normalized union stays on
  `ApiProblem.document`. No screen edit was needed and no validation entry is dropped.
- **The mock gained the three new methods** so the behaviour interface stays a single seam.

**Known gaps.** The 1 skipped vitest case is the compile-time typing test, covered by
`npm run typecheck`. No QA verdict, merge or close.

**Post-rebase update (2026-11-04).** Rebased onto `origin/main` `d620514` (backend contract
alignment, #32 / PR #33). `npm run check:contract` now exits 0 with zero differences;
`npm run generate:api` still produces no diff; `make lint && make test` passes with 74 backend
unit + 38 frontend passed + 1 skipped. The original drift is resolved; PR #31 is ready for QA.

## Session 24 — 2026-11-04: align the generated OpenAPI with the frozen contract (#32)

**What I asked for.** Implement issue #32: make FastAPI's generated OpenAPI document match the
frozen `openapi.yaml` structurally so the T3.1 check on PR #31 exits 0 with no baseline or
allowlist. Runtime bodies and status codes stay unchanged; the contract is the authority.

**What AI did.**

- Added `backend/api/schemas.py` with Pydantic models named exactly as the contract's components:
  `Problem`, `ProblemError`, `ValidationProblemError`, `StockRow`, `Movement`, `Order`, `OrderLine`,
  `Product`, `ReceiveRequest`, `AdjustRequest`, `CreateOrderLine`, `CreateOrderRequest`,
  `InvariantViolation`, `InvariantReport`, `Health` and `Version`. `WithJsonSchema` and
  `json_schema_extra` pin the OpenAPI 3.0 `nullable`/`oneOf`/`not` spellings Pydantic does not emit.
- Added `backend/api/openapi.py` with a custom `app.openapi` generator. It installs the `allOf`
  problem variants (`InsufficientStockProblem`, `InvalidTransitionProblem`,
  `WouldBreachReservedProblem`, `NegativeOnHandProblem`, `ValidationProblem`, `NotFoundProblem`,
  `ServiceUnavailableProblem`), the `#/components/parameters` and `#/components/responses` the
  contract references, and replaces FastAPI's inline path/query parameters with those refs.
- Declared `status_code=201` and `response_model` on create order, receive and adjust; added
  `response_model` to every read endpoint and `responses` refs for 404/409/422/503/default.
- Renamed the order routes to `{id}` and kept the Python argument as `order_id` via `Path(alias="id")`.
- Renamed `HealthResponse`/`VersionResponse` to `Health`/`Version` so the component names match.
- Made the request models strict so `"3"`, `1.5` and `True` stay 422, and kept the hand-written
  validators (duplicate-line aggregation, non-zero delta, blank adjust note, unknown SKU).
- Preserved the malformed-JSON detail by teaching the validation handler about Pydantic's
  `json_invalid` error type; status, type and shape are unchanged.
- Added `tests/unit/test_openapi_contract.py` pinning the drift classes the check found.

**Verified myself.**

- `node frontend/scripts/check-contract.mjs` (copied temporarily from the #27 worktree, then
  removed): 70 differences before, 0 after, exit 0.
- Red path: renamed `StockRow.low` to `is_low`, saw 3 differences and exit 1, restored the file and
  re-ran to 0 differences / exit 0.
- Every `$ref` in the generated document resolves; 25 schemas, 2 parameters, 7 response components.
- `make test-integration`: 120 passed. `make lint`: ruff, `tsc -b` and eslint clean.
  `make test`: 70 unit and 10 frontend passed.
- Existing integration tests still assert the same runtime bodies and statuses; no integration
  assertion was changed because none encoded the old declared status.

**Overruled / changed.**

- **Pydantic now validates request bodies before the handlers.** Valid requests are unchanged and
  every rejected request is still a 422 problem+json; only some `detail`/`errors[]` text differs.
  Keeping the hand-written checks means the contract's business rules did not move.
- **`json_invalid` keeps the old detail.** FastAPI parses the body before the endpoint, so malformed
  JSON no longer reaches the `JSONDecodeError` handler; the validation handler now recognises it.

**Known gaps.** The generated document reports OpenAPI `3.1.0` while `openapi.yaml` is `3.0.3`; the
#31 script compares structure, not the version field, so this does not fail the check. FastAPI also
adds a `description` beside response `$ref`s. Both are documentation-level follow-ups if the
contract later gains a version assertion.

## Session 26 — 2026-11-04: Phase 3 screens in parallel

**What I asked for.** Run T3.2, T3.3 and T3.4 in parallel, with disjoint write scopes so three
engineers could not collide on shared components or the API seam.

**What AI did.**

- **T3.2 (#28 / PR #34)**: `InventoryScreen` on the real hooks, with the low marker, receive and
  adjust dialogs, `409`/`422` problem rendering, refetch-only counters, the four states and the
  accessibility contract. SE commit `16ee652`; QA merged `116cad0`.
- **T3.3 (#29 / PR #35)**: `PlaceOrderScreen` with live SKU search, one line per SKU, trimmed
  customer reference, success refetch, per-line `409 insufficient_stock`, `422` envelopes and
  accessibility. SE commits `ffa4601`/`e3476b4`; QA added `PlaceOrderScreen.qa.test.tsx` (3 tests)
  and merged `af96966`.
- **T3.4 (#30 / PR #36)**: `OrdersScreen` with status filter, newest-first list, in-place detail,
  snapshotted prices, movement timeline, cancel/fulfil gating and `409`/`404` notices. SE commit
  `af4a9ae`; QA added `OrdersScreen.qa.test.tsx` (4 tests) and merged `8a6eeb8`.
- Each engineer wrote only its screen and test files. Shared components, `frontend/src/api/**`,
  `frontend/src/test/**`, package files, the backend and the report were read-only.
- QA verified each screen independently, added tests only, merged one issue at a time and closed
  #28, #29 and #30. This entry also resolves #37 (the missing T3.3 report entry).

**Verified myself.**

- CI green on all three PRs; post-merge proofs at `116cad0`, `af96966` and `8a6eeb8`.
- Final suite: 74 backend unit, 90 frontend passed / 1 skipped; lint clean; contract check 0.
- QA revert evidence covered the low boundary and refetch, receive/adjust validation, the
  per-line `409`, the success refetch and trimmed reference, duplicate-line aggregation, the
  status filter and selection reset, cancel/fulfil gating and `409` resync, timeline order and
  running balance, and the `404` notice. Gaps QA found were covered with its added tests:
  negative quantity and the trimmed 3–40 reference on #29; the fulfil-side `409` and `Fulfilling…`
  pending state on #30.
- `gh issue view 28/29/30` are CLOSED; `main` is `8a6eeb8`.

**Overruled / changed.**

- **Parallel work used screen-only write scopes.** The issues allowed edits to existing
  components; the parallel override made shared-component changes follow-ups instead.
- **Shared `ProblemNotice` improvements are deferred.** T3.3 renders `type` and `errors[]` in the
  screen because the shared component does not; folding that into `ProblemNotice` is a follow-up.
- **The LOW marker** is a DOM text node `Low` made uppercase by CSS; the accessible text remains
  read correctly, so it was accepted as satisfying US6-AC1.
- **The report entries were deferred** to the orchestrator to avoid three branches editing the
  same file; this session entry covers all three issues and closes #37.

**Known gaps.** `ProblemNotice` should eventually render `type`/`errors[]` itself; an empty
customer reference disables submit without an inline message (non-AC usability); the `!inList`
404 fallback is untested because the contract forbids the case. Phase 4 (T4.1–T4.4) is next and
not yet filed; Playwright remains deferred to that phase.

## Session 27 — 2026-11-04: Phase 4 tests in parallel

**What I asked for.** Groom and dispatch the four Phase 4 test tasks, running them in parallel with
disjoint write scopes.

**What AI did.**

- PM filed #38 (unit gaps + `_docs/testing-guidelines.md`), #39 (integration audit), #40
  (live-server concurrency) and #41 (Playwright + inventory-table vitest), with explicit scopes.
- Four engineers ran in parallel:
  - **#38**: added 23 unit cases across quantity validation, availability math, note/reason rules
    and the US1-AC3 coverage-gap note; unit suite 74 → 97.
  - **#39**: audited every listed integration AC; all but one clause was already asserted. Added
    `test_ac_coverage.py` for the missing per-line availability assertion; suite 120 → 121.
  - **#40**: added `test_concurrency.py` — 50 iterations of 20-way contention (one 201, nineteen
    409, no 500s), the two-SKU opposite-order variant, live `uvicorn` on an ephemeral port, and
    cleanup; 1,000 requests.
  - **#41**: added Playwright config, four journeys, a self-starting/tearing-down `make e2e` (free
    ports, `E2E_BASE_URL`), and the missing inventory-table boundary vitest; 4 e2e passed twice.
- QA verified the four in parallel and kept merges serialized. #38 initially FAILed only on a
  documentation row (it named a US3-AC2 test as the US2 owner); the engineer fixed
  `_docs/testing-guidelines.md`, QA re-verified, and merged. #39, #40 and #41 passed first time.

**Verified myself.**

- Merges: `857984b` (#38), `e0971aa` (#39), `4c22aa6` (#40), `22981e2` (#41); all four issues
  CLOSED and `main` green in CI.
- Final suite: **97 unit, 91 frontend (+1 skipped), 124 integration, 4 Playwright**; lint and the
  contract check clean.
- QA red proofs covered every new assertion and the lock-removal red path (the concurrency test
  fails with `IntegrityError` at iteration 0 without `FOR UPDATE`).
- Post-merge proofs ran in clean worktrees at each merge commit.

**Overruled / changed.**

- **#38's docs row was wrong and got fixed**, not waived. The US2 ownership now points at
  `test_concurrency.py`/T4.3 and names the pre-#40 gap honestly.
- **Testing guidelines were stale after T4.4.** The e2e prerequisite and "target does not exist"
  text now describe the self-starting `make e2e`.
- **One PR revert row was not reproducible.** #41's `toBeVisible()` claim passes before refetch;
  QA recorded the corrected invert. The assertion remains meaningful.
- **E2E stays local.** CI was intentionally left unchanged, so Playwright is a local/QA command in
  this phase.

**Known gaps.** Integration, concurrency and e2e are not CI-gated; `make test` remains unit +
frontend; the OpenAPI version text is still `3.1.0` vs `3.0.3`; `ProblemNotice` still does not
render `type`/`errors[]` itself. Phase 5 (ship) is next, with #12 (T5.4) for rollback and release
docs.

## Template

```markdown
## Session N — <date>: <topic>

**What I asked for.**

**What AI did.** (bulleted, specific)

**Verified myself.** (how, not just what)

**Overruled / changed.** (and why)

**Known gaps.** (what is still unproven)
```
