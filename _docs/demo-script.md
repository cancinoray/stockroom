# Demo script (3 minutes)

**Status:** the script for T8.3 (#70) AC1–AC3. The recording (AC4), the three peer reviews (AC5) and
the submission form (AC6) are **human gates**; no agent records, submits or closes anything.

**What this is:** one recording plan that maps the nine beats in [_docs/plan.md](plan.md) §6 to the
rubric rows they prove. Each beat states its screen, exact command or URL, precondition, rubric
criterion and per-beat time budget. The budgets sum to **2:56**, leaving **0:04** inside the 3:00
cap.

**Scope:** this file is the only change in the PR. `README.md`, the screenshots, the reports, the
handoff, the backlog, code, tests, migrations and `openapi.yaml` are untouched.

## Pre-recording checklist

Run this before you press record. Every command is in the repository; §Command and URL verification
names the file each one was checked against.

### 1. Clean, seeded stack with no leftover demo orders

- [ ] `docker compose down -v` — removes the `stockroom-db` volume and every order from a previous
      take. The seed is idempotent, so `make dev` recreates the same 8 SKUs and 8 opening `receive`
      movements.
- [ ] `make dev` — build and start app + Postgres, migrate and seed. Wait for `docker compose ps` to
      show `(healthy)` and `curl -fsS http://localhost:8000/healthz` to return
      `{"status":"ok","db":"ok"}`.
- [ ] `curl -fsS http://localhost:8000/api/orders` returns `[]` before beat 5. If it is not empty,
      run `docker compose down -v && make dev` again. Never delete orders by hand: the ledger is
      append-only and the seed only adds.
- [ ] If the machine has the untracked `compose.override.yaml` port remap, the app and
      `make observability` publish **18000** instead of **8000**. Record which port you use and use
      that origin everywhere below. The examples assume `8000`.
- [ ] `make e2e` has been run once before recording (it starts its own disposable
      `stockroom-e2e` stack and does not touch the demo volume). Verified: 4 journeys pass, and the
      6 observability specs skip unless `OBSERVABILITY_GRAFANA_URL` is set.

### 2. Browser and terminal hygiene

- [ ] Browser window at least **1280px** wide, 100% zoom, one window, one tab. No bookmarks bar, no
      extensions, no personal tabs, no OS or email/calendar notifications.
- [ ] Use a clean browser profile and a fresh terminal. Clear the screen. No shell history that
      contains tokens, DSNs, emails, customer names or `.env` output.
- [ ] The app has **no client-side URL routes**. The three bay buttons — **Inventory** (A),
      **Place order** (B), **Orders** (C) — switch screens. The only app URL is
      `http://localhost:8000`. Do not type `/inventory`, `/place-order` or `/orders`.
- [ ] AGENTS.md rule 4 applies on camera: seeded SKUs only, no tokens or DSNs, no email or calendar
      notifications.

### 3. Alert and drill state reset

- [ ] If you ran the live drill, stop it: `make observability-down`, then `docker compose down -v`.
- [ ] `curl -fsS http://localhost:9090/api/v1/alerts` must not list `StockroomOrderErrorRateHigh`
      before beat 9. If it does, let the 5m window drain or reset the stack; do not edit the alert.
- [ ] The app must be the clean build, not the drill branch. `docker compose ps` shows the expected
      image, and `curl -fsS http://localhost:8000/api/version` answers. Do not record beat 5 on a
      drill build.
- [ ] After recording, reset again: `make observability-down`, then `docker compose down -v`. Do not
      leave a bug build or a firing alert running.

### 4. Local observability and the retention warning

- [ ] `make observability` is up before beats 8–9. It starts app + db plus the OpenTelemetry
      collector, Prometheus, Loki, Tempo, Alloy and Grafana. Wait for all four readiness checks:

      ```bash
                  curl -fsS http://localhost:3000/api/health
                  curl -fsS http://localhost:9090/-/healthy
                  curl -fsS http://localhost:3100/ready
                  curl -fsS http://localhost:3200/ready
                  ```

- [ ] The dashboard is provisioned from files, with no import step:
      `curl -fsS http://localhost:3000/api/dashboards/uid/stockroom-order-journey` returns `200`.
- [ ] **Retention warning:** Prometheus, Loki and Tempo keep data in local Docker volumes on one
      machine; nothing is hosted and there is no retention configuration ([_docs/handoff.md](handoff.md)
      trap 5). Record while the evidence is fresh. Do not plan a "look at last week's dashboard"
      shot.
- [ ] The order used in beat 8 must be placed while `make observability` is up. If beat 5 ran on
      `make dev` (no collector), start `make observability` after beat 5 and place one fresh order on
      the same screen; the `stockroom-db` volume is kept, and the new order's `trace_id` is the one
      to show. Beat 8 states this explicitly.

### 5. Beat 7 host decision (O3)

- [ ] O3 is open as of 2026-11-08: a published tag has never run on the self-hosted host. Decide
      before recording: - **Ideal:** the host is reachable, the current release tag is deployed, and `<host-url>` is a
      real address. Record the real host URL and smoke output. - **Fallback:** O3 is still open. Record the local release tag plus
      `scripts/release-smoke.sh` as a **marked fallback** (beat 7). Say on camera that the public
      host is pending O3. Do not invent a host URL.
- [ ] The deployed URL is the submission form's third field ([_docs/plan.md](plan.md) §7). If O3 is
      open, the human decides whether to submit without a production URL or move O3 first, and
      records that decision on #70. The script does not decide it.

### 6. Video length, format and the README placeholder

- [ ] Length ≤ **3:00**. Format: MP4 (H.264 + AAC) or the course platform's accepted format; 1080p
      or 720p. Upload it and confirm it plays in a logged-out browser.
- [ ] The first frame shows the README with the same screenshots as the merged file (AC7).
- [ ] Replace the placeholder in `README.md` §Demo video. The current line is:

      **Demo video (3 minutes)** — placeholder; T8.3 (#70) replaces this line with the URL. No link yet.

                  Replace the sentence after `**Demo video (3 minutes)** —` with
                  `[Watch the demo](<video-url>)`, keeping the heading. This is the human's one README line; the
                  script does not edit it.

- [ ] No secrets, PII or invented incident/metric. Every number in beat 9 comes from the recorded
      incident named there.

## Runtime budget

| Beat | Topic                                             | Budget | Cumulative |
| ---- | ------------------------------------------------- | ------ | ---------- |
| 1    | README: problem, screens, correctness core        | 0:12   | 0:12       |
| 2    | Spec and tracker: `phase:2` issue, PR #22         | 0:13   | 0:25       |
| 3    | Agent team: process loop, QA PASS                 | 0:13   | 0:38       |
| 4    | Context management: AGENTS.md → domain rule       | 0:10   | 0:48       |
| 5    | App: `make dev`, short line, 409 → 201 → fulfil   | 0:42   | 1:30       |
| 6    | Tests: `make test`, concurrency proof, `make e2e` | 0:22   | 1:52       |
| 7    | Release/CI/CD and the deployment (O3)             | 0:18   | 2:10       |
| 8    | Observability: trace, logs and metric             | 0:26   | 2:36       |
| 9    | Alerting and on-call: recorded incident           | 0:20   | 2:56       |
| —    | Buffer inside the 3:00 cap                        | 0:04   | **3:00**   |

The per-beat budgets are intentional: beats 5 and 8 carry the screen time, because they are the two
beats a reviewer cannot score from a static artifact.

## The nine beats

### Beat 1 — README (0:12)

| Field                   | Value                                                                                  |
| ----------------------- | -------------------------------------------------------------------------------------- |
| **Duration**            | 0:12                                                                                   |
| **Screen / window**     | Browser, one tab, GitHub README on `main`                                              |
| **Exact command / URL** | https://github.com/cancinoray/stockroom                                                |
| **Precondition**        | `main` contains the final README and screenshots (T8.1, #68); logged-out view; 1280px+ |
| **Proves**              | Rubric 1 — problem description                                                         |

**Do this.** Open the repository landing page (the README renders there). Scroll the problem
statement, the three screenshots (Inventory, Place order, Orders) and the "The correctness core"
four rules. Pause on the screenshots; they are the same files AC7 checks in the video's opening
frame.

**Fallback.** None.

### Beat 2 — Spec and tracker (0:13)

| Field                   | Value                                                              |
| ----------------------- | ------------------------------------------------------------------ |
| **Duration**            | 0:13                                                               |
| **Screen / window**     | Browser: `phase:2` issue list, issue #8, PR #22                    |
| **Exact command / URL** | https://github.com/cancinoray/stockroom/issues?q=label%3Aphase%3A2 |
| **Precondition**        | Public tracker; issue #8 is closed and PR #22 is merged            |
| **Proves**              | Rubric 2 — spec + tracker used by agents                           |

**Do this.**

1. Show the filtered list: the eight `phase:2` issues.
2. Open issue #8, `T2.4 Atomic reservation on POST /api/orders`, and read its acceptance criteria
   (US1-AC1..AC5, US2-AC3, I5/I6).
3. Open PR #22, `feat: atomic reservation (#8)`, and show its `Refs #8` body and acceptance-criteria
   checklist.

**Plan deviation (honest).** Plan §6 beat 2 says "one issue open". Every `phase:2` issue is closed
on `main` today; the tracker is complete. Show the completed issue/PR chain. If the project board's
URL is not known, the issue-search URL above is the board's data; say so.

**Terminal alternative.** `gh issue list --label phase:2 --state all --limit 8` and
`gh pr view 22`.

**Fallback.** None; the issue and PR exist on `main`.

### Beat 3 — Agent team and the QA verdict (0:13)

| Field                   | Value                                                                         |
| ----------------------- | ----------------------------------------------------------------------------- |
| **Duration**            | 0:13                                                                          |
| **Screen / window**     | Browser: `_docs/process.md` §4 loop diagram, then the QA PASS comment         |
| **Exact command / URL** | https://github.com/cancinoray/stockroom/blob/main/_docs/process.md#4-the-loop |
| **Precondition**        | The QA PASS comment dated 2026-11-01 exists on issue #8                       |
| **Proves**              | Rubric 3 — agent team                                                         |

**Do this.** Show the mermaid loop (PM → Engineer → QA → merge), then open the QA verdict:
https://github.com/cancinoray/stockroom/issues/8#issuecomment-6559668502 and show the per-AC
`PASS`/`FAIL` list. That is the **pre-merge** verdict (2026-11-01T15:01:58Z): it records that
nothing is merged, so do not leave it on screen beside the merged PR #22. Name the **post-merge**
verdict for the same issue as the later comment,
https://github.com/cancinoray/stockroom/issues/8#issuecomment-6559807977 (2026-11-01T15:13:33Z),
which re-checks the ACs at the squash merge `90f4a43` and records the close.

**Plan deviation (honest).** Plan §6 beat 3 says "the QA verdict comment on that PR".
[_docs/process.md](process.md) §5 puts the verdict **on the issue**; PR #22 is the linked
implementation. Show the issue comment (the canonical location) and say that in one sentence.

**Fallback.** If the comment anchor moves, open issue #8 and scroll to `## QA: PASS` (pre-merge) or
`## QA: post-merge PASS` (the later verdict).

### Beat 4 — Context management (0:10)

| Field                   | Value                                                       |
| ----------------------- | ----------------------------------------------------------- |
| **Duration**            | 0:10                                                        |
| **Screen / window**     | Browser: `AGENTS.md`, then `_docs/domain.md` §3             |
| **Exact command / URL** | https://github.com/cancinoray/stockroom/blob/main/AGENTS.md |
| **Precondition**        | Both files are on `main`                                    |
| **Proves**              | Rubric 4 — context management                               |

**Do this.** Show the `Documents` table in `AGENTS.md` and click `_docs/domain.md`. Stop at
**§3 Reservation transaction**:
https://github.com/cancinoray/stockroom/blob/main/_docs/domain.md#3-reservation-transaction. Read
the ordered `SELECT ... ORDER BY sku FOR UPDATE`, the validation inside the lock, and the single
transaction. That is the rule `AGENTS.md` rule 2 points to.

**Fallback.** None.

### Beat 5 — The app and the single command (0:42)

| Field                   | Value                                                                                                                      |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **Duration**            | 0:42                                                                                                                       |
| **Screen / window**     | Terminal, then browser at `http://localhost:8000`                                                                          |
| **Exact command / URL** | `docker compose down -v && make dev` then `http://localhost:8000`                                                          |
| **Precondition**        | Pre-built image (run `make dev` once before recording so the build is a cache hit); no leftover orders; browser at 1280px+ |
| **Proves**              | Rubric 5 and 7 — application + single command                                                                              |

**Do this.**

1. Run `docker compose down -v && make dev`. `make dev` stays in the foreground; leave it running
   and open `http://localhost:8000` from a second window. Wait for `(healthy)` in
   `docker compose ps` first.
2. Click **Place order**. Customer reference: `CUST-DEMO`.
3. Add `SKU-8820` (3 on hand) and set Qty `4`. Add `SKU-1042` (18 on hand) and set Qty `2`.
4. Click **Reserve stock**. The `409 insufficient_stock` notice names `SKU-8820` (requested 4,
   available 3, short by 1) and says no stock was reserved. The `SKU-1042` line is untouched.
5. Change `SKU-8820` to Qty `3` and click **Reserve stock**. The notice shows the order confirmed,
   `201`, both lines reserved.
6. Click **Orders**, open the `CUST-DEMO` order and click **Fulfil order**. The status becomes
   `fulfilled`; the movement timeline shows the `ship`.
7. Click **Inventory** and show `SKU-8820` on hand 0 / available 0, and `SKU-1042` available
   `18 - 2 = 16`. The stock position chart drops.

**Why these numbers.** The seed opens `SKU-8820` at 3 on hand with a reorder point of 2, so Qty 4
is short by exactly 1; Qty 3 is the all-or-nothing success that ships the last units. The second
line proves the failed order did not half-reserve the healthy SKU.

**Telemetry continuity.** If you record the order on `make dev`, it predates the collector and has
no Tempo trace. Before beat 8, run `make observability` and place one more `CUST-DEMO` order; the
`stockroom-db` volume and the earlier order survive. Use the new order's `trace_id` in beat 8. The
alternative is to start `make observability` before beat 5 and show `make dev` as a separate
five-second clip.

**Fallback.** If the image build is slow, cut from the command to the healthy stack. Never fake the
order response.

### Beat 6 — Tests and the concurrency proof (0:22)

| Field                   | Value                                                                             |
| ----------------------- | --------------------------------------------------------------------------------- |
| **Duration**            | 0:22                                                                              |
| **Screen / window**     | Terminal                                                                          |
| **Exact command / URL** | `make test`; `uv run pytest tests/integration/test_concurrency.py -q`; `make e2e` |
| **Precondition**        | `make install` has run; Docker is available for the integration harness and e2e   |
| **Proves**              | Rubric 6 — testing; and the headline "no oversell under concurrency"              |

**Do this.**

1. `make test` — show the backend unit summary (291 passed) and the frontend summary (91 passed,
   1 skipped). This is the Makefile target; `make test-unit` and `make test-frontend` are its parts.
2. `uv run pytest tests/integration/test_concurrency.py -q` — show the three passing tests. This is
   the documented targeted form; `make test-integration` is the Makefile target, and
   [_docs/handoff.md](handoff.md) trap 8 explains why `-k` is not appended to a make target.
3. `make e2e` — show the Playwright summary: 4 journeys passed, 6 observability specs skipped
   because `OBSERVABILITY_GRAFANA_URL` is unset. The skipped specs belong to beat 8, not this beat.

**Plan deviation (honest).** Plan §6 beat 6 says the concurrency log "shows 1 × 201 / 19 × 409".
The test asserts exactly one `201` and nineteen `409` per iteration over 50 iterations (1,000
requests), but pytest prints only its result, not the counts. The assertion is at
`tests/integration/test_concurrency.py:499-503`. Show the passing test and the assertion lines;
do not pretend the log prints the counts.

**Fallback.** If the full `make test` is too slow on camera, pre-run it and show the tail. The
command and the result are real.

### Beat 7 — Release, CI/CD and deployment (0:18)

| Field                   | Value                                                                                                                        |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Duration**            | 0:18                                                                                                                         |
| **Screen / window**     | Browser: the latest `CI` run on `main`; terminal on the host (ideal) or locally (fallback); smoke output                     |
| **Exact command / URL** | https://github.com/cancinoray/stockroom/actions                                                                              |
| **Precondition**        | The release job has run on `main`; GHCR is public-read; Docker on the host. Ideal requires O3 closed and a real `<host-url>` |
| **Proves**              | Rubric 8 and 9 — deployment and CI/CD                                                                                        |

**Do this (ideal, O3 closed).** Show the green `CI` run and the `publish the release image` job
summary with the tag. Say: "CI publishes the tag; it never deploys." Then run on the host, from the
repository root:

```bash
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:<release-tag> docker compose pull app
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:<release-tag> docker compose run --rm app alembic upgrade head
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:<release-tag> docker compose up -d
scripts/release-smoke.sh <host-url>
docker compose ps
docker compose ps -q app | xargs docker inspect --format '{{.Config.Image}}'
```

`<release-tag>` is the tag from the job summary. The latest verified tag at the time of writing is
`20261108-144014-ff1c4fb` (run
https://github.com/cancinoray/stockroom/actions/runs/42490709942). `scripts/release-smoke.sh`
defaults to `http://localhost:8000` and accepts one optional base URL; pass `<host-url>` for the
host. The smoke must exit `0` with all three checks.

**Do this (fallback, O3 open — the current state).** Say the public host is pending O3. Show the
same tag running locally and the smoke passing:

```bash
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:20261108-144014-ff1c4fb docker compose pull app
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:20261108-144014-ff1c4fb docker compose up -d
scripts/release-smoke.sh
docker compose ps
docker compose ps -q app | xargs docker inspect --format '{{.Config.Image}}'
```

If the local port override remaps the app, run `scripts/release-smoke.sh http://localhost:18000`.
Do not use `make dev` or `make observability` for this shot: both pass `--build`, which would
rebuild a local image under the release tag instead of running the pulled artifact
([_docs/release-process.md](release-process.md) §4). Do not use `<new-tag>` as a literal; read the
tag from the job summary.

**Fallback, clearly marked.** The local release-tag run is a **fallback, not the ideal**. It proves
the published artifact and the smoke script; it does not prove a public host. The public deployed
URL remains O3's deliverable.

### Beat 8 — Observability: one trace, logs and the metric (0:26)

| Field                   | Value                                                                                                |
| ----------------------- | ---------------------------------------------------------------------------------------------------- |
| **Duration**            | 0:26                                                                                                 |
| **Screen / window**     | Browser: Grafana dashboard, Tempo trace, Loki log line, Prometheus query                             |
| **Exact command / URL** | `make observability`; dashboard at http://localhost:3000/d/stockroom-order-journey                   |
| **Precondition**        | `make observability` is up; the order was placed while it was up (see the continuity note in beat 5) |
| **Proves**              | Rubric 10 — observability                                                                            |

**Do this.**

1. Open the dashboard: http://localhost:3000/d/stockroom-order-journey. Show the five panels: Orders
   placed, Orders failed by reason, p95 request latency, Reservation conflicts, Invariant drift.
2. Get the order's trace id from the app's JSON log line:

   ```bash
   docker compose logs --no-log-prefix --since 10m app | grep -F 'POST /api/orders' | tail -1
   ```

   Copy the `"trace_id"` value (32 hex characters).

3. Open Grafana Explore and query Tempo by trace id. The direct URL is the documented Explore
   search with the id substituted:

   ```text
   http://localhost:3000/explore?left=%7B%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queries%22%3A%5B%7B%22refId%22%3A%22A%22%2C%22datasource%22%3A%7B%22type%22%3A%22tempo%22%2C%22uid%22%3A%22tempo%22%7D%2C%22queryType%22%3A%22traceId%22%2C%22query%22%3A%22<TRACE_ID>%22%7D%5D%2C%22range%22%3A%7B%22from%22%3A%22now-1h%22%2C%22to%22%3A%22now%22%7D%7D
   ```

   Replace `<TRACE_ID>` with the 32-hex id. Show the `POST /api/orders` span and the SQL child spans.

4. In Grafana Explore, select the Loki datasource and run the same id through LogQL:

   ```logql
   {container=~"stockroom-app.*"} | json | trace_id="<TRACE_ID>"
   ```

   Show the JSON log line. The trace id is in the log body, not a separate index.

5. Show the metric for the same service and environment: the dashboard's "Orders placed" panel, or
   the Prometheus query:

   ```bash
   curl -s 'http://localhost:9090/api/v1/query?query=stockroom_orders_placed_total' | python3 -m json.tool
   ```

   The app's telemetry puts the active span id on the log line and the metric exemplar
   ([_docs/operations-and-security-report.md](operations-and-security-report.md) §5), so the
   trace id is the join key. The dashboard shows the aggregate metric; it has no per-trace filter,
   so say that and show the trace, the log line and the metric panel together.

**Precondition / continuity.** If beat 5 ran on `make dev`, its order has no Tempo trace because
the collector was not running. Start `make observability` after beat 5 and place one fresh
`CUST-DEMO` order; the db volume is kept and the new order's trace is the one to show. This is the
honest way to satisfy "the trace for the order placed in beat 5" without pretending the earlier
request was exported.

**Fallback.** If Grafana Explore misbehaves, use the Prometheus query and the Loki API. Do not show
Grafana Cloud: O4 is superseded and the local `make observability` stack is the verified path.

### Beat 9 — Alerting and on-call (0:20)

| Field                   | Value                                                                                   |
| ----------------------- | --------------------------------------------------------------------------------------- |
| **Duration**            | 0:20                                                                                    |
| **Screen / window**     | Browser/terminal: Prometheus alert rules, the recorded incident, the fix PR             |
| **Exact command / URL** | `on-call-engineer/incidents/stockroom-order-error-rate-high-a697e0be6f0f-1794071189.md` |
| **Precondition**        | `make observability` is up for the alert-rules shot; no live alert needs to be firing   |
| **Proves**              | Rubric 11 and 12 — alerting and on-call                                                 |

**Do this.**

1. Open http://localhost:9090/alerts and show the three rules and their expressions.
2. Open the recorded incident:
   `on-call-engineer/incidents/stockroom-order-error-rate-high-a697e0be6f0f-1794071189.md`
   (https://github.com/cancinoray/stockroom/blob/main/on-call-engineer/incidents/stockroom-order-error-rate-high-a697e0be6f0f-1794071189.md).
   It records `StockroomOrderErrorRateHigh` at 44.4% (24 of 54 local requests), threshold 5%,
   `for: 1m`, the evidence inspected, the hypothesis, the policy decisions, the 8.727s responder run
   of a 600s budget, and verified recovery at 2026-11-07T17:15:55Z.
3. Open the responder's fix PR: https://github.com/cancinoray/stockroom/pull/67. It is **closed**,
   not merged; it is evidence. Say the responder cannot merge or deploy and a human decides.
4. Say the recorded responder is the **deterministic drill responder**, not an autonomous model run;
   the incident's `review.notes` says so. Do not claim more than the record.

**Why this is the fallback (plan deviation).** Plan §6 beat 9 says "inject the failure flag, alert
fires, responder runs, incident report + fix PR appear". There is **no runtime failure flag** in the
repository. The only drill injects a code bug with
`on-call-engineer/drills/fulfil-last-units-500/bug.patch` on a throwaway branch, and the live
sequence needs a 5m rate window plus a 1m hold while the responder has a 600s budget — longer than
the whole video. The recorded incident is the honest evidence. The live drill commands are in the
appendix for a separate, pre-recorded run if the human wants them.

**Fallback.** The recorded incident above. If you re-run the live drill, record it separately and
cut it in; do not stretch beat 9 past 0:20.

## Fallbacks and plan deviations (summary for QA)

| Plan §6 says                                       | What `main` has today                                               | What this script does                                                       |
| -------------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Beat 2: "one issue open"                           | All eight `phase:2` issues are closed                               | Shows the completed issue #8 → PR #22 chain; states the tracker is complete |
| Beat 3: "QA verdict comment on that PR"            | The verdict is on issue #8 per `_docs/process.md` §5                | Shows the issue comment and the linked PR; states the canonical location    |
| Beat 6: concurrency log "shows 1 × 201 / 19 × 409" | The test asserts the counts; pytest prints only the result          | Shows the passing test and the assertion lines; states the log limitation   |
| Beat 7: deploy the tag to the self-hosted host     | O3 is open; no published tag has run on the host                    | Ideal commands plus a clearly marked local release-tag + smoke fallback     |
| Beat 8: the beat-5 order's trace                   | The trace exists only if telemetry was up when the order was placed | Starts `make observability` and places a fresh order if needed; states why  |
| Beat 9: "inject the failure flag"                  | No runtime flag; the drill injects a code bug and takes >3:00       | Shows the recorded 2026-11-07 incident, alert rule, and closed fix PR #67   |

No beat is silently dropped. Every fallback is marked on screen and repeated here.

## Human handoff

### What the human records

1. Record beats 1–9 (or record in a different order and edit; the on-screen evidence is what
   matters). Keep the total ≤ 3:00.
2. Follow the pre-recording checklist. Do not record secrets, PII, email/calendar notifications or
   shell history.
3. Upload the video and confirm it plays while logged out.
4. Replace the README placeholder with the video URL (checklist §6). That is the only README change
   this issue owns.
5. Post the video URL on #70 and record the AC4 result.

### What QA re-checks after AC4 (AC7)

From a logged-out browser:

- [ ] The README video link resolves and plays.
- [ ] The repository URL resolves: https://github.com/cancinoray/stockroom
- [ ] The deployed URL resolves — or the O3 decision is recorded on #70 if there is no deployed URL.
- [ ] The video's opening frame shows the README with the same screenshots as the merged file:
      `_docs/screenshots/inventory.png`, `_docs/screenshots/place-order.png` and
      `_docs/screenshots/orders.png`.
- [ ] Post the link-check result on #70. This is the post-AC4 link check, not a merge or close.

### Peer reviews (AC5)

- Three peer reviews on the course platform; each **pass/fail**, recorded on #70 with its date and
  the project reviewed.
- Budget ~3h ([_docs/handoff.md](handoff.md) O7). A missing review fails the project regardless of
  the build ([_docs/plan.md](plan.md) §7).
- Do them before the deadline. The deadline is O1 and is still unconfirmed; do not invent a date.

### Submission (AC6)

- Repository URL, video URL and deployed URL, submitted before the deadline.
- Post the confirmation on #70, or a screenshot where the platform gives no receipt.
- AC6 depends on O3 for the deployed URL. If O3 is open, the human decides whether to submit without
  a production URL or move O3 first, and records that decision on #70. The script does not decide it,
  and no agent submits.

## Command and URL verification

Every command and URL above was checked against the repository. "Ran" means it was executed in this
worktree on 2026-11-08; "not started" means the command exists but was not run because a local
stack was already running and starting another would have replaced it.

| Item                                                                         | Checked against                                                                            | Status                                                                               |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `make dev`                                                                   | `Makefile:52-53`; `README.md` §Run it locally; `compose.yaml`                              | Exists; not started in this session                                                  |
| `make test`                                                                  | `Makefile:26`; ran in this worktree                                                        | Passed: 291 backend unit, 91 frontend (1 skipped)                                    |
| `make test-unit`                                                             | `Makefile:16-17`; ran                                                                      | 291 passed                                                                           |
| `make test-integration`                                                      | `Makefile:19-20`; `tests/integration/conftest.py`                                          | Exists; the full suite was not run                                                   |
| `uv run pytest tests/integration/test_concurrency.py -q`                     | `tests/integration/test_concurrency.py`; ran                                               | 3 passed in 11.8s                                                                    |
| `make e2e`                                                                   | `Makefile:104-106`; `tests/e2e/run-e2e.sh`; ran                                            | 4 journeys passed; 6 observability specs skipped without `OBSERVABILITY_GRAFANA_URL` |
| `make observability`                                                         | `Makefile:60-61`; `compose.observability.yaml`; `observability/README.md`                  | Exists; not started in this session                                                  |
| `make observability-down`                                                    | `Makefile:63-64`                                                                           | Exists                                                                               |
| `make check-alerts`                                                          | `Makefile:69-73`; ran                                                                      | `SUCCESS: 3 rules found`                                                             |
| `make oncall-poll ARGS=--once`                                               | `Makefile:78-79`; `observability/README.md`; drill README                                  | Exists; the exact make form is `ARGS=--once`                                         |
| `make oncall-respond INCIDENT=<id>`                                          | `Makefile:85-87`; `on-call-engineer/run-responder.sh`; drill log                           | Exists; the recorded invocation is in the appendix                                   |
| `make oncall-verify INCIDENT=<id>`                                           | `Makefile:92-94`; `on-call-engineer/verify-recovery.sh`                                    | Exists                                                                               |
| `docker compose down -v`                                                     | `README.md` §Data, stopping and ports; `_docs/deployment.md` §6                            | Exists                                                                               |
| `scripts/release-smoke.sh`                                                   | `scripts/release-smoke.sh`; `_docs/deployment.md` §5; ran against `http://localhost:18000` | Passed all three checks                                                              |
| Release pull/migrate/swap commands                                           | `_docs/release-process.md` §2–§3; `docker manifest inspect` for the example tag            | Exists; the example tag is public-read                                               |
| `docker compose ps` / `docker compose ps -q app \| xargs docker inspect ...` | `_docs/release-process.md` §3                                                              | Exists                                                                               |
| App URL `http://localhost:8000`                                              | `compose.yaml` (`8000:8000`); `README.md` §One command                                     | Exists; `18000` with the local override                                              |
| `http://localhost:3000/d/stockroom-order-journey`                            | `observability/README.md` §The dashboard and trace links                                   | Exists                                                                               |
| `http://localhost:3000/explore`                                              | `observability/README.md` §The dashboard and trace links                                   | Exists                                                                               |
| `http://localhost:9090` and `http://localhost:9090/alerts`                   | `compose.observability.yaml`; `observability/README.md`                                    | Exists                                                                               |
| `http://localhost:3100/ready`                                                | `compose.observability.yaml`; `observability/README.md`                                    | Exists                                                                               |
| `http://localhost:3200/ready`                                                | `compose.observability.yaml`; `observability/README.md`                                    | Exists                                                                               |
| GitHub repo, issue, PR and Actions URLs                                      | `README.md`; `_docs/backlog.md`; `gh issue view 8`; `gh pr view 22`; `gh run list`         | Resolve; the QA comment URL was read from the GitHub API                             |

## Appendix — the live drill (separate from the 3:00 video)

This is optional. Beat 9 uses the recorded incident. If the human wants a fresh firing, run this
outside the 3-minute recording and cut the evidence in. It is the procedure in
`on-call-engineer/drills/fulfil-last-units-500/README.md`, kept here only so the exact commands are
in one place. It is **not** a 3-minute beat: the alert needs a 5m window plus a 1m hold and the
responder budget is 600s. The recorded base is `5f957b5196ab489a687ec1179f5f3c3ce57ce9af`; if
`origin/main` has moved, follow the drill README's re-record instruction rather than applying
`bug.patch` to a newer base.

```bash
# 1. Inject the drill bug on a throwaway branch; never on main.
git fetch origin
git switch -c drill/p7-fulfil-last-units-500 5f957b5196ab489a687ec1179f5f3c3ce57ce9af
git apply on-call-engineer/drills/fulfil-last-units-500/bug.patch
make lint
make test
make test-integration
git add backend/api/orders.py
git commit -m "drill: two-statement fulfil counter update (#63)"
git push -u origin drill/p7-fulfil-last-units-500

# 2. Local stack with the drill build identity.
# Untracked and machine-local: compose.yaml sets neither STOCKROOM_COMMIT nor
# STOCKROOM_BUILD_TIME (_docs/deployment.md §4), so the alert would report
# version "0.1.0"/"unknown". `make observability` appends this file only when it
# exists. Keep any existing port remap (the app is published on 18000 where the
# local override says so): append a second YAML document instead of replacing the
# file, so a local `ports: !override` remap survives.
printf '\n---\n' >> compose.override.yaml
cat >> compose.override.yaml <<YAML
services:
  app:
    environment:
      STOCKROOM_COMMIT: "$(git rev-parse drill/p7-fulfil-last-units-500)"
      STOCKROOM_BUILD_TIME: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
YAML
make reset          # requires STOCKROOM_DATABASE_URL pointed at the local Compose database
make observability
curl -s localhost:8000/api/version | python3 -m json.tool   # :18000 with the port remap

# 3. Traffic that exposes the bug; let the 5m window hold the failures.
# Use http://localhost:18000 here and in step 5 when the local override remaps the port.
STOCKROOM_APP_URL=http://localhost:8000 \
  sh on-call-engineer/drills/fulfil-last-units-500/drive-traffic.sh
curl -s localhost:9090/api/v1/alerts | python3 -m json.tool

# 4. Exactly one evidence packet.
ONCALL_BASE_REF=drill/p7-fulfil-last-units-500 \
ONCALL_BASE_COMMIT="$(git rev-parse drill/p7-fulfil-last-units-500)" \
  make oncall-poll ARGS=--once

# 5. The responder. The operator's gh CLI supplies GH_TOKEN; never print or commit it.
#    RESPONDER_CMD is an operator-supplied JSON argv array. The child runs with the
#    isolated worktree as its CWD, so copy the committed responder outside that
#    worktree first (the recorded run used /tmp/drill/responder-drill.py):
#      mkdir -p /tmp/drill
#      cp on-call-engineer/drills/fulfil-last-units-500/responder-drill.py /tmp/drill/
#    The exact recorded invocation is in drill-log.md section AC3.
RESPONDER_CMD='["python3","/tmp/drill/responder-drill.py"]' \
STOCKROOM_APP_URL=http://localhost:8000 ONCALL_BUDGET_SECONDS=600 \
  make oncall-respond INCIDENT=<incident-id>

# 6. Verified recovery after the fix.
make observability-down
git switch oncall/<incident-id>
make observability
sleep 360
make oncall-verify INCIDENT=<incident-id>
```

The drill branch and its `bug.patch` are evidence on a throwaway branch; `main` never contains the
bug. Stop the drill stack and reset the demo with `make observability-down` and
`docker compose down -v` before recording beat 5 or beat 9.
