#!/usr/bin/env bash
# Post-deploy smoke check for a self-hosted Stockroom host (T5.3, issue #48,
# AC10). One copy-pasteable command, three checks, non-zero exit on any
# failure — run it after `docker compose up -d` swaps in a new release tag:
#
#   scripts/release-smoke.sh                              # http://localhost:8000
#   scripts/release-smoke.sh http://192.168.1.20:8000
#
# Checks: GET /healthz is ok (liveness + database), GET / serves the built
# React UI, and GET /api/version answers with the release metadata.
set -u

BASE="${1:-http://localhost:8000}"
BASE="${BASE%/}"
FAIL=0
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

ok()   { printf 'ok    %s\n' "$*"; }
bad()  { printf 'FAIL  %s\n' "$*"; FAIL=1; }

# --- /healthz: 200, status ok, database ok ----------------------------------
if ! BODY="$(curl -fsS --max-time 10 "$BASE/healthz" 2>&1)"; then
  bad "/healthz: request failed: $BODY"
elif [[ "$BODY" != *'"status":"ok"'* ]]; then
  bad "/healthz: expected status ok, got: $BODY"
elif [[ "$BODY" != *'"db":"ok"'* ]]; then
  bad "/healthz: expected db ok, got: $BODY"
else
  ok "/healthz -> $BODY"
fi

# --- GET /: 200, text/html, the built app root -------------------------------
if ! META="$(curl -fsS --max-time 10 -o "$TMP" -w '%{http_code} %{content_type}' "$BASE/" 2>&1)"; then
  bad "GET /: request failed: $META"
elif [[ "$META" != 200* ]]; then
  bad "GET /: expected 200, got: $META"
elif [[ "$META" != *text/html* ]]; then
  bad "GET /: expected text/html, got: $META"
elif ! grep -q 'id="root"' "$TMP"; then
  bad "GET /: response is not the built UI (no app root element)"
else
  ok "GET / -> $META, app root present"
fi

# --- /api/version: 200, release metadata ------------------------------------
if ! BODY="$(curl -fsS --max-time 10 "$BASE/api/version" 2>&1)"; then
  bad "/api/version: request failed: $BODY"
elif [[ "$BODY" != *'"version"'* || "$BODY" != *'"commit"'* ]]; then
  bad "/api/version: missing version/commit fields: $BODY"
else
  ok "/api/version -> $BODY"
fi

if [ "$FAIL" -ne 0 ]; then
  echo "smoke FAILED against $BASE"
  exit 1
fi
echo "smoke passed against $BASE"
