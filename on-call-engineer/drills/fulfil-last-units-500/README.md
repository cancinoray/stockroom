# Drill `fulfil-last-units-500` (issue #63, T7.3)

**Status: PROPOSED — awaiting the AC1 human gate. Nothing has been injected.** This directory is an
inert harness: `bug.patch` has not been applied, no drill branch exists, no stack has been started
with the bug and no alert, packet or incident exists for this drill. The AC1 approval comment URL is
recorded below once a human has approved the paragraph, before any injection.

| Field | Value |
| --- | --- |
| Drill id | `fulfil-last-units-500` |
| Recorded base | `5f957b5196ab489a687ec1179f5f3c3ce57ce9af` (`origin/main`, "feat: responder task, autonomy policy and headless run (#62) (#65)") |
| Bug branch (not created yet) | `drill/p7-fulfil-last-units-500`, from the recorded base |
| Expected alert | `StockroomOrderErrorRateHigh` — `observability/alerts.yaml`, 5xx on the order-journey routes above 5% of requests over a 5m window, `for: 1m` |
| Expected impact | `POST /api/orders/{id}/fulfil` returns `500 unexpected` whenever the order takes every remaining free unit of a SKU |
| Approval comment (this is the AC1 gate) | _PLACEHOLDER — to be filled with the issue #63 approval comment URL after a human approves the paragraph below; the same URL goes in `drill-log.md`_ |
| Injection | Human gate. Nobody applies `bug.patch` until the approval URL above exists. |

## The proposed bug (the paragraph a human approves)

The fulfil path writes the two cached stock counters as two separate `UPDATE` statements instead of
the single atomic update it uses today: it lowers `stock.on_hand` for the shipped quantity first and
only then lowers `stock.reserved`. `_docs/domain.md` §2 puts an immediate table check on that row
(`check (reserved <= on_hand)`), so the first statement is already invalid whenever the shipped
quantity is larger than the units still free after the order's own reservation. In practice that is
the ordinary case of a customer taking the last units of a SKU: the order reserves everything that
was available, and when the warehouse clicks **Fulfil order** the request fails with a `500`. The
order stays `confirmed`, its reservation is never released, the units never ship, availability stays
at zero and every retry fails the same way until someone cancels the order by hand. A few such
orders in a row push the order-journey 5xx ratio over the 5% rule threshold, so
`StockroomOrderErrorRateHigh` fires; nothing else changes — no counter drifts from the ledger,
because the failed transaction rolls back.

Why this is a legitimate drill bug rather than a planted failure:

- It is a plain logic error in the order/stock path: two statements where the invariant requires
  one. It is the exact hazard `_docs/domain.md` §2 says the database check exists to convert into a
  failed transaction, and the error ordering ("ship the goods, then drop the hold") is a natural
  refactor of the current ORM counter update into the SQL-update shape the reservation path already
  uses.
- It is reachable only through the real order journey: `POST /api/orders` for the remaining
  available units, then `POST /api/orders/{id}/fulfil` — the same two requests the Place order
  screen and the Orders lane's **Fulfil order** button send.
- It is not a `sleep`, `raise`, feature flag, test edit or hidden endpoint, and it changes no test.
- `make test` and `make test-integration` pass on the bug branch, because no existing test fulfils an
  order whose quantity exceeds the units still free at fulfil time. The suite fulfils small
  quantities against deep stock (2 of 18, 3 of 40) and the concurrency suite drives reservation
  contention and cancels, never a ship against an exhausted SKU.

The failure condition, stated so the responder can falsify it: with `available = on_hand - reserved`
read under the order's lock, the first statement fails when `on_hand - qty < reserved`, which is
exactly `available < qty`. The current code writes both columns in one `UPDATE`, so the same request
returns `200`.

## What the patch touches

`bug.patch` is a unified diff against `backend/api/orders.py` at the recorded base:
12 insertions, 3 deletions, one file, no test change. It replaces the counter update at the end of
`_transition_order` with two `session.execute(update(Stock) ...)` statements (the `update` import
already exists for the reservation path), keeping the existing comment and adding one that explains
the wrong-but-plausible reasoning.

`git apply --check` against the recorded base:

```text
$ git apply --check -v on-call-engineer/drills/fulfil-last-units-500/bug.patch
Checking patch backend/api/orders.py...
```

The patch is inert in this branch's history: it is a file under `on-call-engineer/drills/`, not a
change to product code. `origin/main` never contains the bug.

## Planned commands (all blocked on AC1 approval)

Run every command below from the drill worktree, on this machine, against the local Compose project
only. No production host, no production credentials, no SQL against any database, no secret.

### 1. Inject on the drill branch, prove AC1

```bash
git fetch origin
git rev-parse origin/main                         # must equal the recorded base; if it moved, re-record the base and regenerate bug.patch first

git switch -c drill/p7-fulfil-last-units-500 5f957b5196ab489a687ec1179f5f3c3ce57ce9af
git apply --check on-call-engineer/drills/fulfil-last-units-500/bug.patch
git apply on-call-engineer/drills/fulfil-last-units-500/bug.patch
git diff --stat                                   # backend/api/orders.py only; no test file

make lint
make test                                        # AC1: unit + frontend suites
make test-integration                            # AC1: httpx against a real Postgres
git add backend/api/orders.py
git commit -m "drill: two-statement fulfil counter update (#63)"
git push -u origin drill/p7-fulfil-last-units-500
```

### 2. Local stack with the drill build identity

```bash
# Untracked and machine-local: compose.yaml sets neither STOCKROOM_COMMIT nor
# STOCKROOM_BUILD_TIME (_docs/deployment.md §4), so the alert would report
# version "0.1.0"/"unknown". `make observability` appends this file only when it
# exists. Keep any existing port remap (the app is published on 18000 where the
# local override says so). Record the exact file in drill-log.md.
cat > compose.override.yaml <<YAML
services:
  app:
    environment:
      STOCKROOM_COMMIT: $(git rev-parse drill/p7-fulfil-last-units-500)
YAML

make reset                                       # local seeded reset; STOCKROOM_DATABASE_URL must point at the local compose database
make observability
curl -s localhost:8000/api/version | python3 -m json.tool   # commit must be the drill sha (use :18000 with the port remap)
```

### 3. Traffic that exposes the bug (AC2)

```bash
STOCKROOM_APP_URL=http://localhost:8000 \
  sh on-call-engineer/drills/fulfil-last-units-500/drive-traffic.sh

# The 500s are the bug. Let the 5m window hold the failures, then read the alert.
curl -s localhost:9090/api/v1/alerts | python3 -m json.tool
# record pendingAt and activeAt for StockroomOrderErrorRateHigh in drill-log.md
```

### 4. Exactly one evidence packet (AC2)

```bash
ONCALL_BASE_REF=drill/p7-fulfil-last-units-500 \
ONCALL_BASE_COMMIT="$(git rev-parse drill/p7-fulfil-last-units-500)" \
  make oncall-poll ARGS=--once
ls -la on-call-engineer/evidence/                # record the packet path and incident id
```

### 5. Headless responder (AC3)

```bash
make oncall-respond INCIDENT=<incident-id>        # 600s budget; the record lands in on-call-engineer/incidents/
```

### 6. Verified recovery (AC4)

```bash
make observability-down
git switch oncall/<incident-id>                  # the responder's fix branch, PR base drill/p7-fulfil-last-units-500
make observability                               # build and start the fixed branch locally
sleep 360                                        # outlast the rule's 5m window plus its 1m hold
make oncall-verify INCIDENT=<incident-id>        # must exit 0
```

### 7. Record and sign-off

Fill `drill-log.md` from the commands above, with real outputs only. The human reviewer records the
verdict and the fix-PR approval comment URL there; the responder's own `review.status` stays
`pending`. The harness and the incident record reach `main` later in the docs/ops PR for AC6.

## Boundaries

- Local Compose project only. No deploy, no merge, no image push, no production host or credential.
- The only product-code change is `bug.patch` on `drill/p7-fulfil-last-units-500` and the responder's
  fix on `oncall/<incident-id>`; `main` never contains either.
- No test is edited to make the bug pass and no counter is hand-fixed.
- `on-call-engineer/verify-recovery.sh` is the recovery authority, not a green log line.
