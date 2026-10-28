# AI Usage Report

What AI did, what I checked, and what I overruled. One entry per working session, written by
whoever did the work (human or agent) before the session is considered finished.

The rule: an entry says what was **verified**, not what was **produced**. "Generated a
Dockerfile" is not an entry; "generated a Dockerfile, built it, ran the app from it, and removed
the build-only layer that leaked a token into the image" is.

## Session log

| # | Date | Phase | Tool / agent | Task | Produced | Verified how | Overruled / changed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-27 | P0 | AI coding agent (planning session) | Scope the project, write spec and process | README, product-spec, AGENTS.md, domain/process/plan/backlog docs | Rubric read from the course repo; starter repo inspected; estimates reconciled against phase totals | See notes below |
| 2 | 2026-10-27 | P0 | AI coding agent (planning session) | Align the repo with the course article series (parts 1–5) | `_docs/` layout, task template, team roles, `.agents/agents` + `.agents/skills`, reworked process and plan | Each article read in the primary source; conventions cross-checked against the rubric wording; links and paths verified | See notes below |
| 3 | _pending_ | P0 | | Tracker setup (T0.4) | | | |
| 4 | 2026-10-27 | P0 | AI coding agent (repo cleanup) | Remove the vendor-specific agent entry point | Vendor-specific entry file and symlink tree removed; docs point only at `AGENTS.md` and `.agents/` | Repo-wide search for the vendor name returns nothing; every documented path resolves | See notes below |
| 5 | 2026-10-27 | P0 | AI coding agent (process) | Make concurrent multi-agent execution explicit and break the plan into dispatchable tasks | `_docs/process.md` concurrency rules; `_docs/plan.md` §2.1 task map | Every task id checked against `_docs/backlog.md`; lane order checked against phase dependencies and the D5–D6 schedule | See notes below |
| 6 | 2026-10-27 | P1 | AI coding agent (backend subagent + parent) | Build T1.1 backend skeleton and T1.2 mocked React prototype | FastAPI app factory/settings/health/version + tests; Vite/React/Tailwind/TanStack mock-backed Inventory, Place order and Orders; Makefile targets | `make lint` and `make test` (2 backend, 7 frontend); production build; Playwright drove the short-line 409, fulfil, cancel and a 390px viewport; screenshots reviewed | See notes below |
| 7 | 2026-10-27 | P1 | AI coding agent (UI) | Add a per-SKU stock chart to the Inventory screen | `StockChart` component, chart styling and Inventory integration | `npm run lint`, `npm run build`, `npm test`; measured bar widths in the running dev server; desktop and 390px screenshots reviewed | See notes below |
| 8 | 2026-10-27 | P1 | AI coding agent (design) | Document the implemented front-end design as a reusable system | `_docs/design-system.md`; README, AGENTS and handoff links | Tokens cross-checked against `index.css`; component rules checked against the screens and the live dev server at 1440px and 390px | See notes below |
| 9 | 2026-10-27 | P1 | AI coding agent (UI fixes) | Close the modal-focus and quantity-validation gaps | Shared focus-trap hook, order-line validation, two regression tests, test cleanup | `make lint`, `make test` (9 frontend) and production build; focus trap/restore exercised in jsdom | See notes below |
| 10 | 2026-10-28 | P1–P2 | AI coding agent (orchestrator + four PM subagents) | Groom every open issue, reconcile the backlog mirror, dispatch #3/#5/#7 | Groomed tracker #1–#12 (#12 filed), `_docs/backlog.md` mirror, three worktrees on `feat/3-*`, `feat/5-*`, `feat/7-*` | Every edited issue re-read with `gh issue view`; AC count and seed size counted from the spec/domain, not the issues; `make test` (2 backend, 9 frontend) green at `b6de97a`; `git worktree list` | See notes below |

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
- That Render/Fly/Railway/Cloud Run are acceptable deployment targets (Module 3 states this
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

## Session 10 — 2026-10-28: grooming all open issues and dispatching P1/P2

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

**Verified myself.**

- Re-read every edited issue body after the edit; labels and the four template sections intact.
- Counted the ACs from `product-spec.md` §6 (US1 5 + US2 3 + US3 3 + US4 3 + US5 5 + US6 4 = 23)
  and the seeded catalogue from `_docs/domain.md` §6 (8 products); both differed from the issue text.
- Checked the `Makefile` before accepting any proof command: `migrate`, `seed`, `reset` and
  `test-integration` do not exist yet, so #5/#6 now own adding them rather than citing them.
- `make test`: 2 backend and 9 frontend tests pass; `make lint` had already passed on this commit.
- Confirmed Docker and Compose are available before telling #5 to provision its own test Postgres.

**Overruled / changed.**

- **24 ACs → 23.** The count was a miscount in the backlog and #3; the spec needed no version bump.
- **Six SKUs → eight.** The issue was the only document that disagreed with the domain and backlog.
- **Rollback in T1.4 → #12.** A first deploy has nothing to roll back to; the rehearsal belongs in P5.
- **#2’s toggle ACs.** Re-scoped rather than implemented: building debug toggles into the throwaway
  prototype buys nothing once the contract is frozen, and Phase 3 owns visible error states.
- **#1 left closed-readiness alone.** Its issue text is satisfied; the spec’s DB probe moves to #5.
- **#4 queued behind #5.** Both edit `Makefile`; the file-ownership rule matters more than lane count.

**Known gaps.** #1 and #2 still need a QA verdict and a close. #4 cannot pass its deploy AC until a
human provisions Fly and `FLY_API_TOKEN`. T3.1–T3.4 and T5.1–T5.3 have no issues yet by design.
Engineer PRs for #3, #5 and #7 are in flight and are not covered by this entry.

## Template

```markdown
## Session N — <date>: <topic>

**What I asked for.**

**What AI did.** (bulleted, specific)

**Verified myself.** (how, not just what)

**Overruled / changed.** (and why)

**Known gaps.** (what is still unproven)
```
