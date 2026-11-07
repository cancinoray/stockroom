#!/usr/bin/env python3
"""Deterministic drill responder for issue #63 (T7.3) — DRILL USE ONLY.

This is NOT an autonomous agent and does not pretend to be one. It is a fixed
procedure written for `drill fulfil-last-units-500`, committed under
`on-call-engineer/drills/fulfil-last-units-500/` and run through the real T7.2
runner (`run_responder.py`), so it gets the runner's isolated worktree, its
allowlisted PATH of policy shims, its isolated HOME, its process-group budget
and its response validation.

What it does, in order: read the packet; ask the policy before every
consequential action and record each answer verbatim; open one failing trace
in Tempo; reproduce the 500 against the local stack; write the regression test
into the worktree and run it against the packet's base (must fail); apply the
smallest fix and run it again (must pass); commit, push `oncall/<incident-id>`
and open exactly one PR whose base is the packet's `repo.base_ref`; write the
response document the runner validates.

Limitations, stated so nobody mistakes this for a headless agent run:

* the diagnosis is not open-ended — it is the approved drill bug, and the
  procedure is a script rather than a model reading the evidence;
* the `claude` CLI is installed on the host but cannot authenticate under the
  runner's isolated HOME (`Not logged in`), and the runner does not pass a
  model credential to the child, so no model ran;
* `docker run` is denied by the docker shim, so the regression test reuses the
  local Compose Postgres through `STOCKROOM_TEST_DATABASE_URL` and creates its
  own throwaway database beside it, exactly as the repo's `_fresh_database`
  helper is designed to;
* it uses the operator's installed dev environment (`<repo>/.venv`) because the
  isolated worktree has none; the code under test is always the worktree's.

The run's credential is `GH_TOKEN` in the child environment. This script never
reads, prints or copies it; git gets it through the runner's askpass helper.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BUDGET_SECONDS = int(os.environ.get("ONCALL_BUDGET_SECONDS") or 600)
STARTED = time.monotonic()

PACKET_PATH = Path(os.environ["ONCALL_PACKET_PATH"])
WORKTREE = Path(os.environ["ONCALL_WORKTREE"])
RESPONSE_PATH = Path(os.environ["ONCALL_RESPONSE_PATH"])
POLICY_PATH = Path(os.environ["ONCALL_POLICY_PATH"])
POLICY_PY = Path(os.environ["ONCALL_POLICY_PY"])
TASK_PATH = Path(os.environ["ONCALL_TASK_PATH"])
INCIDENT_ID = os.environ["ONCALL_INCIDENT_ID"]
BASE_REF = os.environ["ONCALL_BASE_REF"]
BASE_COMMIT = os.environ["ONCALL_BASE_COMMIT"]
BRANCH = f"oncall/{INCIDENT_ID}"

APP_URL = os.environ.get("STOCKROOM_APP_URL", "http://localhost:8000").rstrip("/")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
TEMPO_URL = "http://localhost:3200"

TEST_RELATIVE = "tests/integration/test_fulfil_last_units_drill.py"
SOURCE_RELATIVE = "backend/api/orders.py"
ARTIFACT_DIR = Path("/tmp/drill")

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

DECISIONS: list[dict[str, str]] = []


class Abort(Exception):
    """Stop the procedure and record a non-fix outcome instead of guessing."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# -- output ------------------------------------------------------------------


def log(message: str) -> None:
    print(f"[drill-responder] {message}", flush=True)


def artifact(name: str, text: str) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / name
    path.write_text(text, encoding="utf-8")
    return path


# -- policy ------------------------------------------------------------------


def decide(action: str, context: dict[str, object]) -> dict[str, str]:
    """Ask the policy CLI; record the answer verbatim; refuse anything not allowed."""
    completed = subprocess.run(
        [
            sys.executable,
            str(POLICY_PY),
            "--action",
            action,
            "--context-json",
            json.dumps(context, sort_keys=True),
            "--policy",
            str(POLICY_PATH),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        decision = json.loads(completed.stdout)
    except ValueError:
        raise Abort(
            "policy_unreadable",
            f"policy CLI gave no JSON for {action!r}: {completed.stderr.strip()[:200]}",
        ) from None
    for key in ("action", "decision", "rule_id", "reason"):
        if not isinstance(decision.get(key), str) or not decision[key]:
            raise Abort("policy_unreadable", f"policy decision for {action!r} lacks {key!r}")
    DECISIONS.append({key: decision[key] for key in ("action", "decision", "rule_id", "reason")})
    log(f"policy {action} -> {decision['decision']} ({decision['rule_id']})")
    if decision["decision"] != "allow":
        raise Abort(
            "policy_refused",
            f"the policy answered {decision['decision']} for {action!r} ({decision['rule_id']})",
        )
    return decision


# -- local HTTP --------------------------------------------------------------


def http_json(url: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int, object]:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in LOCAL_HOSTS:
        raise Abort("non_local_endpoint", f"{host!r} is not the local stack")
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else None
        except ValueError:
            parsed = body
        return exc.code, parsed


# -- evidence ----------------------------------------------------------------


def inspect_trace(trace_id: str) -> dict[str, object]:
    try:
        status, body = http_json(f"{TEMPO_URL}/api/traces/{trace_id}")
    except Exception as exc:  # noqa: BLE001 - an unreadable trace is reported, not fatal
        return {"trace_id": trace_id, "status": None, "error": type(exc).__name__}
    names: list[str] = []
    if status == 200 and isinstance(body, dict):
        for batch in body.get("batches", []):
            for scope in batch.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    names.append(str(span.get("name")))
    return {"trace_id": trace_id, "status": status, "spans": names}


def reproduce() -> dict[str, object]:
    """The same request shape the UI sends, against the running buggy build."""
    status, stock = http_json(f"{APP_URL}/api/stock")
    if status != 200 or not isinstance(stock, list):
        raise Abort("reproduce_failed", f"GET /api/stock returned {status}")
    rows = {row["sku"]: row for row in stock}
    sku = ""
    for candidate in ("SKU-8820", "SKU-4410", "SKU-5127", "SKU-2087"):
        if int(rows.get(candidate, {}).get("available", 0)) > 0:
            sku = candidate
            break
    if not sku:
        raise Abort("reproduce_failed", "no seeded SKU has available units to take")
    qty = int(rows[sku]["available"])

    place_status, placed = http_json(
        f"{APP_URL}/api/orders",
        method="POST",
        payload={"customer_ref": "DRILL-RESP-1", "lines": [{"sku": sku, "qty": qty}]},
    )
    if place_status != 201 or not isinstance(placed, dict):
        raise Abort("reproduce_failed", f"placing the order returned {place_status}")
    order_id = str(placed["id"])

    fulfil_status, fulfil_body = http_json(f"{APP_URL}/api/orders/{order_id}/fulfil", method="POST")
    # Leave the stack as it was found: the reservation is released again.
    cancel_status, _ = http_json(f"{APP_URL}/api/orders/{order_id}/cancel", method="POST")
    invariants_status, invariants = http_json(f"{APP_URL}/api/invariants")

    result = {
        "sku": sku,
        "qty": qty,
        "order_id": order_id,
        "place_status": place_status,
        "fulfil_status": fulfil_status,
        "fulfil_body_type": (fulfil_body or {}).get("type")
        if isinstance(fulfil_body, dict)
        else None,
        "cancel_status": cancel_status,
        "invariants_status": invariants_status,
        "invariants": invariants,
    }
    artifact("responder-reproduction.json", json.dumps(result, indent=2, sort_keys=True) + "\n")
    log(f"reproduced: POST /api/orders/{order_id}/fulfil -> {fulfil_status}")
    if fulfil_status != 500:
        raise Abort(
            "not_reproduced",
            f"the fulfil returned {fulfil_status}, not the 500 the packet's alert describes",
        )
    return result


# -- the fix -----------------------------------------------------------------

REGRESSION_TEST = '''"""Drill regression guard (incident {incident_id}).

An order that takes every remaining available unit of a SKU must still be
fulfillable. The ship lowers `on_hand` and `reserved` together, so the row's
immediate `reserved <= on_hand` check holds at every statement: exactly the
case that fails when the two counters are written separately.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.config import get_settings
from backend.db import seed as seed_module
from backend.main import app
from tests.integration.test_seed import _fresh_database, _run_alembic


@pytest.fixture()
def client(database_url: str, monkeypatch: pytest.MonkeyPatch):
    with _fresh_database(database_url) as url:
        _run_alembic(url, "upgrade", "head")
        engine = create_engine(url, pool_pre_ping=True)
        try:
            monkeypatch.setenv("STOCKROOM_DATABASE_URL", url)
            get_settings.cache_clear()
            seed_module.seed(engine)
            with TestClient(app) as test_client:
                yield SimpleNamespace(client=test_client, engine=engine)
        finally:
            get_settings.cache_clear()
            engine.dispose()


def test_a_fulfil_that_takes_every_free_unit_succeeds(client) -> None:
    rows = {{row["sku"]: row for row in client.client.get("/api/stock").json()}}
    sku = "SKU-8820"
    available = rows[sku]["available"]
    on_hand = rows[sku]["on_hand"]
    assert available > 0

    placed = client.client.post(
        "/api/orders",
        json={{"customer_ref": "DRILL-LAST-1", "lines": [{{"sku": sku, "qty": available}}]}},
    )
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["id"]

    fulfilled = client.client.post(f"/api/orders/{{order_id}}/fulfil")

    assert fulfilled.status_code == 200, fulfilled.text
    assert fulfilled.json()["status"] == "fulfilled"
    assert sorted(m["reason"] for m in fulfilled.json()["movements"]) == ["reserve", "ship"]

    with client.engine.connect() as connection:
        counters = connection.execute(
            text("SELECT on_hand, reserved FROM stock WHERE sku = :sku"), {{"sku": sku}}
        ).one()
    assert (counters.on_hand, counters.reserved) == (on_hand - available, 0)
    assert client.client.get("/api/invariants").json() == {{"ok": True, "violations": []}}
'''

BUGGY_BLOCK = """        # Cancel returns the reservation; fulfil removes the goods and the hold.
        # Each counter is written with its own statement, the shape the
        # reservation path uses, so the order writes read the same way.
        for line in domain_lines:
            stock = stock_by_sku[line.sku]
            if target is OrderStatus.FULFILLED:
                session.execute(
                    update(Stock)
                    .where(Stock.warehouse_id == order.warehouse_id, Stock.sku == line.sku)
                    .values(on_hand=stock.on_hand - line.qty, updated_at=now)
                )
            session.execute(
                update(Stock)
                .where(Stock.warehouse_id == order.warehouse_id, Stock.sku == line.sku)
                .values(reserved=stock.reserved - line.qty, updated_at=now)
            )
"""

FIXED_BLOCK = """        # Cancel returns the reservation; fulfil removes the goods and the hold.
        # Both counters move in one UPDATE: the table check (reserved <=
        # on_hand) is immediate, so a separate on_hand write would reject the
        # intermediate row whenever the order takes the last free units.
        for line in domain_lines:
            stock = stock_by_sku[line.sku]
            stock.reserved -= line.qty
            if target is OrderStatus.FULFILLED:
                stock.on_hand -= line.qty
            stock.updated_at = now
"""


def write_regression_test() -> str:
    path = WORKTREE / TEST_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(REGRESSION_TEST.format(incident_id=INCIDENT_ID), encoding="utf-8")
    return TEST_RELATIVE


def apply_fix() -> None:
    path = WORKTREE / SOURCE_RELATIVE
    text = path.read_text(encoding="utf-8")
    if text.count(BUGGY_BLOCK) != 1:
        raise Abort("fix_not_applicable", "the expected counter block is not in the worktree")
    path.write_text(text.replace(BUGGY_BLOCK, FIXED_BLOCK), encoding="utf-8")


def test_python() -> str:
    repo_root = WORKTREE.parent.parent
    candidate = repo_root / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def run_regression_test(label: str) -> tuple[int, str]:
    python = test_python()
    env = dict(os.environ)
    env["STOCKROOM_TEST_DATABASE_URL"] = (
        "postgresql+psycopg://stockroom:stockroom@127.0.0.1:5432/stockroom"
    )
    env.pop("STOCKROOM_DATABASE_URL", None)
    remaining = max(int(BUDGET_SECONDS - (time.monotonic() - STARTED) - 90), 30)
    try:
        completed = subprocess.run(
            [python, "-m", "pytest", TEST_RELATIVE, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=WORKTREE,
            env=env,
            capture_output=True,
            text=True,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired:
        output = f"{label}: pytest exceeded {remaining}s"
        artifact(f"responder-test-{label}.log", output + "\n")
        raise Abort("test_budget_exhausted", output) from None
    output = completed.stdout + completed.stderr
    artifact(f"responder-test-{label}.log", f"$ {python} -m pytest {TEST_RELATIVE} -q\n{output}")
    return completed.returncode, output


# -- git and the PR ----------------------------------------------------------


def git(*arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=WORKTREE, capture_output=True, text=True, timeout=120
    )
    if check and completed.returncode != 0:
        raise Abort("git_failed", f"git {' '.join(arguments)}: {completed.stderr.strip()[:300]}")
    return completed.stdout.strip()


def repository() -> str:
    completed = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        cwd=WORKTREE,
        capture_output=True,
        text=True,
        timeout=120,
    )
    slug = completed.stdout.strip()
    if completed.returncode != 0 or "/" not in slug:
        raise Abort("gh_failed", f"gh repo view: {completed.stderr.strip()[:200]}")
    return slug


def open_pr(failing: str, passing: str) -> str:
    body = "\n".join(
        [
            "## Drill fix (issue #63, T7.3)",
            "",
            f"Incident `{INCIDENT_ID}`; base is the drill branch `{BASE_REF}`, not `main`.",
            "This PR is drill evidence. It is not for `main` and nobody merges it.",
            "",
            "### Cause",
            "",
            "`_transition_order` wrote `stock.on_hand` and `stock.reserved` as two",
            "separate UPDATEs. The table check `reserved <= on_hand` is immediate, so the",
            "first statement rejected the intermediate row whenever the shipped quantity",
            "exceeded the units still free — the ordinary case of an order taking the last",
            "available units. `POST /api/orders/{id}/fulfil` returned 500 and the units",
            "never shipped.",
            "",
            "### Fix",
            "",
            "Move both counters in one UPDATE, so the row only ever holds valid states.",
            "",
            "### Regression guard",
            "",
            f"`{TEST_RELATIVE}` fails on `{BASE_REF}` and passes here.",
            "",
            "<details><summary>failing on the drill base</summary>",
            "",
            "```",
            failing.strip()[-1800:],
            "```",
            "",
            "</details>",
            "",
            "<details><summary>passing with the fix</summary>",
            "",
            "```",
            passing.strip()[-1800:],
            "```",
            "",
            "</details>",
            "",
            "Refs #63",
        ]
    )
    artifact("responder-pr-body.md", body + "\n")
    completed = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            BASE_REF,
            "--head",
            BRANCH,
            "--title",
            f"fix: keep the fulfil counters atomic ({INCIDENT_ID})",
            "--body",
            body,
        ],
        cwd=WORKTREE,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        raise Abort("pr_failed", f"gh pr create: {completed.stderr.strip()[:300]}")
    url = completed.stdout.strip().splitlines()[-1].strip()
    artifact("responder-pr-url.txt", url + "\n")
    return url


# -- response ----------------------------------------------------------------


def base_document(action: str, **extra: object) -> dict[str, object]:
    document: dict[str, object] = {
        "incident_id": INCIDENT_ID,
        "alert": {
            "name": "",
            "severity": None,
            "environment": None,
            "version": None,
            "dashboard_url": None,
            "rule": {"expr": None, "for": None},
        },
        "user_impact": "",
        "evidence_inspected": [],
        "hypothesis": "",
        "action": action,
        "changes": {
            "files": [],
            "test": None,
            "branch": None,
            "base_ref": BASE_REF,
            "worktree": str(WORKTREE),
            "pr_url": None,
        },
        "policy": {"version": "1", "sha256": "0" * 64, "decisions": DECISIONS},
        "verification": {"status": "not_run", "checks": [], "observed_at": None},
        "timing": {
            "started": "1970-01-01T00:00:00Z",
            "ended": "1970-01-01T00:00:00Z",
            "elapsed_seconds": 0,
            "budget_seconds": BUDGET_SECONDS,
        },
        "detection_gap": "",
        "escalation": None,
        "review": {
            "status": "pending",
            "notes": "Deterministic drill responder (issue #63). It cannot sign off its own work.",
        },
    }
    document.update(extra)
    return document


def write_response(document: dict[str, object]) -> None:
    RESPONSE_PATH.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def escalation(reason: str, detail: str) -> None:
    document = base_document(
        "escalate",
        hypothesis=detail,
        user_impact="The drill responder stopped before proposing a fix; see the escalation.",
        evidence_inspected=["evidence packet", "local stack"],
        escalation={"decision_required": reason, "context": detail},
        review={
            "status": "pending",
            "notes": "Deterministic drill responder (issue #63); it cannot sign off its own work.",
        },
    )
    write_response(document)


def main() -> int:
    packet = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
    alert = packet["alert"]
    service = packet["service"]
    logs = packet["observations"]["logs"]
    rule = alert.get("rule") or {}

    if Path(os.environ["ONCALL_TASK_PATH"]) != TASK_PATH or not TASK_PATH.exists():
        pass  # the runner appends its task path; it is informational here

    log(f"incident {INCIDENT_ID}: {alert['name']} at {alert.get('value')}")

    decide("read.packet", {})
    decide("read.repo", {"path": SOURCE_RELATIVE})
    decide("read.local_endpoint", {"host": "localhost"})
    decide("git.worktree.create", {})
    decide("git.branch.create", {"branch": BRANCH})

    # Evidence before code: one failing trace from the packet.
    trace_ids = [t for t in logs.get("trace_ids", []) if isinstance(t, str)]
    traces = [inspect_trace(t) for t in trace_ids[:2]]
    trace_note = "; ".join(
        f"{t['trace_id']} ({len(t.get('spans') or [])} spans: "
        f"{', '.join((t.get('spans') or [])[:8])})"
        for t in traces
    )

    decide("run.tests", {"host": "localhost"})
    reproduction = reproduce()

    decide("edit", {"path": TEST_RELATIVE})
    write_regression_test()
    failing_code, failing_output = run_regression_test("base")
    log(f"regression test on the drill base: exit {failing_code}")
    if failing_code == 0:
        raise Abort(
            "regression_test_did_not_fail",
            "the new test passed on the packet's base, so it does not guard the bug",
        )

    decide("edit", {"path": SOURCE_RELATIVE})
    apply_fix()
    passing_code, passing_output = run_regression_test("fix")
    log(f"regression test with the fix: exit {passing_code}")
    if passing_code != 0:
        raise Abort("fix_did_not_pass", "the regression test still fails with the fix applied")

    decide("git.commit", {"branch": BRANCH})
    git("add", SOURCE_RELATIVE, TEST_RELATIVE)
    git(
        "commit",
        "-m",
        f"fix: keep the fulfil counters atomic ({INCIDENT_ID})",
        "-m",
        "The ship wrote on_hand and reserved separately, so the immediate "
        "reserved <= on_hand check rejected an order that took the last free "
        "units. One UPDATE keeps every intermediate row valid.",
        "-m",
        "Refs #63",
    )
    commit = git("rev-parse", "HEAD")

    decide("git.push", {"branch": BRANCH, "force": False})
    slug = repository()
    pushed = subprocess.run(
        ["git", "push", f"https://github.com/{slug}.git", BRANCH],
        cwd=WORKTREE,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if pushed.returncode != 0:
        raise Abort("push_failed", f"git push: {pushed.stderr.strip()[:300]}")

    decide("pr.create", {"base_matches_packet": True, "branch": BRANCH})
    pr_url = open_pr(failing_output, passing_output)
    log(f"fix PR: {pr_url}")

    impact = (
        f"Order-journey 5xx reached {float(alert.get('value') or 0):.1%} over the rule's 5m window "
        f"(24 of 54 local requests failed, threshold 5%). Every fulfil of an order that took the "
        f"last free units of a SKU returned 500: the order stayed confirmed, its reservation was "
        f"never released and the units never shipped."
    )
    document = base_document(
        "fix",
        user_impact=impact,
        evidence_inspected=[
            f"evidence packet {PACKET_PATH.name}: alert {alert['name']} = {alert.get('value')}, "
            f"rule for {rule.get('for')}, deployed version {service.get('deployed_version')}",
            f"packet log samples: {len(logs.get('samples') or [])} 5xx lines, "
            f"selector {logs.get('selector')}",
            f"Tempo traces: {trace_note}",
            f"reproduction against the running build: POST /api/orders for all "
            f"{reproduction['qty']} available {reproduction['sku']} -> "
            f"{reproduction['place_status']}, then fulfil -> "
            f"{reproduction['fulfil_status']}, cancel -> {reproduction['cancel_status']}",
            f"GET /api/invariants during the incident: {json.dumps(reproduction['invariants'])}",
            f"regression test {TEST_RELATIVE} on the drill base: pytest exit {failing_code}",
            f"regression test with the fix: pytest exit {passing_code}",
        ],
        hypothesis=(
            "_transition_order wrote stock.on_hand and then stock.reserved as two statements. "
            "The table check reserved <= on_hand is immediate, so the on_hand write alone is "
            "invalid whenever on_hand - qty < reserved, which is exactly available < qty: an "
            "order holding the last free units. The transaction rolls back and the request 500s."
        ),
        changes={
            "files": [SOURCE_RELATIVE, TEST_RELATIVE],
            "test": TEST_RELATIVE,
            "branch": BRANCH,
            "base_ref": BASE_REF,
            "worktree": str(WORKTREE),
            "pr_url": pr_url,
        },
        verification={
            "status": "not_run",
            "checks": [
                "regression test fails on the packet's base and passes with the fix "
                "(recorded above)",
                "recovery is verified after the fix by on-call-engineer/verify-recovery.sh, "
                "outside this run",
            ],
            "observed_at": None,
        },
        detection_gap=(
            "None for detection: the 5% error-rate rule fired about a minute after the failures "
            "began. The gap is in coverage, not alerting: no existing test fulfils an order that "
            "takes the last free units, so only the alert caught it."
        ),
        review={
            "status": "pending",
            "notes": (
                f"Deterministic drill responder for issue #63 (commit {commit}). Not an autonomous "
                "agent run: the claude CLI cannot authenticate under the isolated HOME and no "
                "model credential is passed to the child. The responder cannot sign off its own "
                "work."
            ),
        },
    )
    write_response(document)
    artifact(
        "responder-summary.json",
        json.dumps(
            {
                "commit": commit,
                "pr_url": pr_url,
                "failing_exit": failing_code,
                "passing_exit": passing_code,
                "reproduction": reproduction,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Abort as exc:
        log(f"abort: {exc.reason}: {exc.detail}")
        escalation(exc.reason, exc.detail)
        raise SystemExit(0) from None
    except Exception as exc:  # noqa: BLE001 - the runner needs a response, not a traceback
        log(f"unexpected {type(exc).__name__}: {exc}")
        escalation("responder_error", f"{type(exc).__name__}: {exc}"[:400])
        raise SystemExit(0) from None
