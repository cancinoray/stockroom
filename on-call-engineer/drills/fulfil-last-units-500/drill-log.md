# Drill log — `fulfil-last-units-500`

Skeleton only. **No field below has been filled and no drill has been run.** Every value is
`<unfilled>` until the matching command has actually run; timestamps are copied from a command's
output, never reconstructed. Delete the placeholder line when a field is filled.

| Field | Value |
| --- | --- |
| Drill id | `fulfil-last-units-500` |
| Issue | #63 (T7.3) |
| Recorded base | `5f957b5196ab489a687ec1179f5f3c3ce57ce9af` |
| Bug branch | `drill/p7-fulfil-last-units-500` |
| Expected alert | `StockroomOrderErrorRateHigh` |
| Status | `<unfilled>` — `injected` / `alert firing` / `packet written` / `fix proposed` / `recovery verified` / `signed off` |

## AC1 — approval and injection

- Approver (human): `<unfilled>`
- Approved at (UTC): `<unfilled>`
- Approval comment URL (issue #63): `<unfilled>`
- `bug.patch` sha256: `<unfilled>`
- `git apply --check` output at injection time: `<unfilled>`
- Drill branch tip at injection: `<unfilled>`
- `git diff --stat` on the drill branch: `<unfilled>`
- `make test` — `<unfilled>` (passed/failed, counts, and the pasted tail)
- `make test-integration` — `<unfilled>` (passed/failed, counts, and the pasted tail)
- Test files changed: `<unfilled>` (must be none)

## Environment

- Exact content of the untracked `compose.override.yaml` used for build identity: `<unfilled>`
- `STOCKROOM_COMMIT` value the app reported (`/api/version`): `<unfilled>`
- App port the stack published (8000, or 18000 with the local override): `<unfilled>`
- Stack command used: `<unfilled>` (`make observability`)
- `make reset` run at (UTC) and result: `<unfilled>`

## AC2 — alert and exactly one packet

- Alert name: `StockroomOrderErrorRateHigh`
- Rule threshold and window as read from the packet: `<unfilled>`
- `pendingAt`: `<unfilled>`
- `activeAt` (firing): `<unfilled>`
- Alert value at firing: `<unfilled>`
- `GET /api/v1/alerts` JSON (pasted): `<unfilled>`
- Poller command, with its env: `<unfilled>`
- Evidence packet path: `<unfilled>` (`on-call-engineer/evidence/<incident-id>.json`)
- Incident id: `<unfilled>`
- Packet sha256: `<unfilled>`
- Packet `repo.base_ref` / `repo.base_commit`: `<unfilled>`
- Packet `service`: name, environment, deployed version, owner, dashboard URL: `<unfilled>`
- Packet log-sample count and the trace id(s) it carries: `<unfilled>`
- One trace id opened in the local Grafana/Tempo trace search (URL): `<unfilled>`
- Packets written by the poll run: `<unfilled>` (must be exactly one)

## AC3 — responder (≤ 600s)

- Command: `<unfilled>` (`make oncall-respond INCIDENT=<incident-id>`)
- Worktree: `<unfilled>` (`worktrees/oncall-<incident-id>`)
- `timing.elapsed_seconds` / `timing.budget_seconds`: `<unfilled>`
- Reproduced from the packet (what was reproduced, against which build): `<unfilled>`
- Regression test added (path and name): `<unfilled>`
- Failing run against the buggy base — command and output: `<unfilled>`
- Passing run with the fix — command and output: `<unfilled>`
- Fix-PR URL and its base: `<unfilled>` (base must be `drill/p7-fulfil-last-units-500`, never `main`, never merged)
- `incidents/<incident-id>.json` path and schema check output: `<unfilled>`
- `policy.decisions` — one row per consequential action: `<unfilled>`

  | # | action | decision (`allow`/`deny`/`escalate`) | rule_id |
  | --- | --- | --- | --- |
  | 1 | `<unfilled>` | `<unfilled>` | `<unfilled>` |

- Any action taken outside the policy: `<unfilled>` (must be none)
- Responder's own `review.status`: `<unfilled>` (must stay `pending`)

## AC4 — verified recovery

- Buggy stack stopped at (UTC): `<unfilled>`
- Fixed branch / commit built and started at (UTC): `<unfilled>`
- `sleep` window used and why: `<unfilled>`
- `verify-recovery.sh` (before the fix) — output and exit code: `<unfilled>`
- `verify-recovery.sh` (after the fix) — output and exit code: `<unfilled>` (must be 0)
- Report: `alert_absent`, `impact_below_threshold`, `app_healthz`, `app_invariants`: `<unfilled>`
- Incident `verification.status` / `verification.observed_at`: `<unfilled>` (must be `passed`, after the fixed build started)
- `/api/invariants` at recovery: `<unfilled>`

## AC5 — record, impact and detection gap

- `incidents/<incident-id>.md` path: `<unfilled>`
- Sections present in order (alert, user impact with numbers, evidence inspected, hypothesis, action taken, files changed, PR URL, verification of recovery, detection gap): `<unfilled>`
- User impact with numbers (from the packet, not from imagination): `<unfilled>`
- Detection gap (or an explicit `none`): `<unfilled>`
- Files changed by the fix: `<unfilled>`

## Human sign-off

- Reviewer (human): `<unfilled>`
- Verdict (`approve` / `reject`): `<unfilled>`
- Fix-PR approval or comment URL: `<unfilled>`
- Reviewed at (UTC): `<unfilled>`
- Notes / follow-ups: `<unfilled>`

## AC6 — cleanup and landing

- Fix PR closed (not merged) at: `<unfilled>`
- `drill/p7-fulfil-last-units-500` deleted at: `<unfilled>`
- `oncall/<incident-id>` deleted at: `<unfilled>`
- Docs/ops PR URL carrying this harness and the incident record to `main`: `<unfilled>`
- `make lint` and `make test` on the docs/ops PR: `<unfilled>`
- `make lint` and `make test` on `main` after the QA merge, with the merge commit: `<unfilled>`
- Commit on `origin/main` that contains any of `bug.patch`'s product change: `<unfilled>` (must be none)
