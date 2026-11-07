#!/bin/sh
# The headless incident responder entry point (T7.2, issue #62).
#
#   make oncall-respond INCIDENT=<incident-id>
#
# The runner is `on-call-engineer/run_responder.py`; this wrapper only finds the
# project environment. Everything the runner needs comes from the environment
# documented in `.env.example` (`RESPONDER_CMD`, `ONCALL_BUDGET_SECONDS`) and
# from the evidence packet named by the incident id.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if ! command -v uv >/dev/null 2>&1; then
  echo "oncall: uv is required to run the responder; run make install first" >&2
  exit 2
fi

exec uv run --no-sync --project "$root" python "$root/on-call-engineer/run_responder.py" "$@"
