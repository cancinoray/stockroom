#!/bin/sh
# verify-recovery.sh <incident-id> (T7.2, issue #62).
#
# The recovery check the investigate-alert skill refers to. It reads the
# recorded incident, then proves recovery against the local stack only:
#
#   * Prometheus /api/v1/alerts  — the alert must be absent;
#   * Prometheus /api/v1/query   — the recorded rule expr must return no series,
#                                  i.e. the impact signal is below its threshold;
#   * the app /healthz and /api/invariants — the service is up and the ledger
#     and the cached counters agree.
#
# It prints one machine-readable JSON report on stdout and exits 0 only when
# every check passes. Exit 1 means not recovered (or not provable); exit 2 means
# the incident record could not be read.
#
# Base URLs come from PROMETHEUS_URL and STOCKROOM_APP_URL (the local defaults
# from .env.example). Nothing here needs a credential, and nothing reaches a
# host other than the local stack unless the operator points the URLs elsewhere.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ "$#" -ne 1 ] || [ -z "${1:-}" ]; then
  echo "usage: on-call-engineer/verify-recovery.sh <incident-id>" >&2
  exit 2
fi

python3 - "$root" "$1" <<'PYTHON'
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT, INCIDENT_ID = sys.argv[1], sys.argv[2]
PROMETHEUS = (os.environ.get("PROMETHEUS_URL") or "http://localhost:9090").rstrip("/")
APP = (os.environ.get("STOCKROOM_APP_URL") or "http://localhost:8000").rstrip("/")
INCIDENTS = os.environ.get("ONCALL_INCIDENTS_DIR") or os.path.join(
    ROOT, "on-call-engineer", "incidents"
)
RECORD = os.path.join(INCIDENTS, INCIDENT_ID + ".json")


def emit(report, code):
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(code)


def fetch(base, path, params=None):
    url = base + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


try:
    with open(RECORD, encoding="utf-8") as handle:
        record = json.load(handle)
except OSError:
    emit({"incident_id": INCIDENT_ID, "recovered": False, "error": "no incident record"}, 2)
except ValueError:
    emit({"incident_id": INCIDENT_ID, "recovered": False, "error": "record is not JSON"}, 2)

alert = record.get("alert") if isinstance(record.get("alert"), dict) else {}
rule = alert.get("rule") if isinstance(alert.get("rule"), dict) else {}
name = alert.get("name")
expr = rule.get("expr")

if not isinstance(name, str) or not name:
    emit({"incident_id": INCIDENT_ID, "recovered": False, "error": "record names no alert"}, 2)

checks = []


def check(check_name, ok, detail):
    checks.append({"name": check_name, "ok": bool(ok), "detail": detail})
    return bool(ok)


try:
    status, body = fetch(PROMETHEUS, "/api/v1/alerts")
    alerts = (body.get("data") or {}).get("alerts") or []
    present = [
        item
        for item in alerts
        if isinstance(item, dict)
        and isinstance(item.get("labels"), dict)
        and item["labels"].get("alertname") == name
    ]
    check(
        "alert_absent",
        status == 200 and body.get("status") == "success" and not present,
        "%d %s alert(s) listed" % (len(present), name),
    )
except Exception as exc:  # a check that cannot run is a failed check
    check("alert_absent", False, type(exc).__name__)

if not isinstance(expr, str) or not expr.strip():
    check(
        "impact_below_threshold",
        False,
        "the record has no rule expr, so the impact signal cannot be re-read",
    )
else:
    try:
        status, body = fetch(PROMETHEUS, "/api/v1/query", {"query": expr})
        data = body.get("data") or {}
        result = data.get("result")
        if data.get("resultType") == "scalar" and isinstance(result, list) and len(result) > 1:
            value = float(result[1])
            above = value > 0
            detail = "scalar value %s" % value
        else:
            series = result or []
            above = bool(series)
            detail = "%d series at or above the threshold" % len(series)
        check(
            "impact_below_threshold",
            status == 200 and body.get("status") == "success" and not above,
            detail,
        )
    except Exception as exc:
        check("impact_below_threshold", False, type(exc).__name__)

try:
    status, body = fetch(APP, "/healthz")
    check(
        "app_healthz",
        status == 200 and body.get("status") == "ok",
        "status=%s db=%s" % (body.get("status"), body.get("db")),
    )
except Exception as exc:
    check("app_healthz", False, type(exc).__name__)

try:
    status, body = fetch(APP, "/api/invariants")
    violations = body.get("violations") or []
    check(
        "app_invariants",
        status == 200 and body.get("ok") is True and not violations,
        "ok=%s violations=%d" % (body.get("ok"), len(violations)),
    )
except Exception as exc:
    check("app_invariants", False, type(exc).__name__)

recovered = all(item["ok"] for item in checks)
emit(
    {
        "incident_id": INCIDENT_ID,
        "alert": name,
        "rule": {"expr": expr, "for": rule.get("for")},
        "recovered": recovered,
        "checks": checks,
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    },
    0 if recovered else 1,
)
PYTHON
