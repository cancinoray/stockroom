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

## Template

```markdown
## Session N — <date>: <topic>

**What I asked for.**

**What AI did.** (bulleted, specific)

**Verified myself.** (how, not just what)

**Overruled / changed.** (and why)

**Known gaps.** (what is still unproven)
```
