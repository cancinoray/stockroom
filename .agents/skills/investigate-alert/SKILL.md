---
name: investigate-alert
description: Investigate a fired Stockroom alert from its evidence packet, reproduce it locally, then fix or escalate and write the incident record.
---

# Investigate an alert

Use when an alert fires or when you are asked to run an incident. Produce an incident record, not
just a fix.

1. Read the packet: `on-call-engineer/evidence/<incident-id>.json`. It contains the alert rule,
   threshold, window, environment, deployed version, dashboard URL, failing trace ids, error log
   samples and the last deploys.
2. State the user impact in one sentence with numbers: how many requests, over how long, for which
   journey (`POST /api/orders` placing an order).
3. Open one failing trace id. Read the span that errored and its attributes. Do not open the code
   until you have seen where it failed.
4. Compare the deployed version against the last known good one: what changed in that diff? A
   regression that ships with a deploy is usually in the diff, not in the database.
5. Reproduce locally: `make dev`, then the same request shape with the same data. If you cannot
   reproduce, say so — an unreproducible diagnosis is a hypothesis, not a cause.
6. Decide, and write the decision down:
   - **real bug** → branch, failing test, smallest fix, `make test`, PR. Never merge.
   - **false positive** → explain from the evidence why user impact did not occur.
   - **needs a human** → escalation packet naming the decision required.
7. Fill `on-call-engineer/incidents/<incident-id>.md` per `response.schema.json`, and record what
   `runbooks/verify-recovery.sh` showed after the fix.
8. Note the detection gap: if the alert fired late, or on the wrong signal, fix the alert in the
   same PR as the runbook update.

Guardrails: read-only production, no deploys, no merges, no raw SQL against production, ten-minute
budget, and never hand-fix a stock counter.
