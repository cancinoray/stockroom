#!/bin/sh
# Runs the Playwright journeys for `make e2e`.
#
# Default path: build and start Postgres and the API under the dedicated
# `stockroom-e2e` Compose project (the app publishes a random host port, so
# 8000/18000 never have to be free), pick a free port for the frontend, wait
# for /healthz, run the specs, and always tear the stack down with `down -v` —
# on success and on failure.
#
# `E2E_BASE_URL=http://host:port` skips all of that and runs the specs against
# a UI that is already up.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$repo_root"

# Playwright lives in frontend/node_modules while this script and the specs do
# not, so test-file resolution needs the explicit path.
export NODE_PATH="$repo_root/frontend/node_modules"

playwright() {
  (
    cd "$repo_root/frontend"
    npx playwright test --config ../playwright.config.ts
  )
}

if [ -n "${E2E_BASE_URL:-}" ]; then
  echo "e2e: running against the UI at $E2E_BASE_URL; no stack is started"
  playwright
  exit 0
fi

command -v docker >/dev/null 2>&1 || {
  echo "e2e: docker is required, or set E2E_BASE_URL to a running UI" >&2
  exit 1
}
command -v node >/dev/null 2>&1 || {
  echo "e2e: node is required to pick a free frontend port" >&2
  exit 1
}

compose() {
  docker compose -p stockroom-e2e -f compose.yaml -f tests/e2e/compose.e2e.yaml "$@"
}

cleanup() {
  echo "e2e: tearing the stack down"
  (
    cd "$repo_root"
    compose down -v --remove-orphans >/dev/null 2>&1
  ) || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# A hard-killed earlier run can leave its volume behind; every run starts from
# the seed, so reset the project before starting it.
compose down -v --remove-orphans >/dev/null 2>&1 || true

E2E_UI_PORT=$(node -e '
const net = require("node:net");
const server = net.createServer();
server.on("error", () => process.exit(1));
server.listen(0, "127.0.0.1", () => {
  console.log(server.address().port);
  server.close();
});
')
export E2E_UI_PORT

echo "e2e: starting Postgres and the API under the stockroom-e2e project"
compose up -d --build --wait

app_port=$(compose port app 8000 | sed -n '1p' | awk -F: '{print $NF}')
if [ -z "$app_port" ]; then
  echo "e2e: could not read the API's published port" >&2
  exit 1
fi

E2E_API_TARGET="http://127.0.0.1:$app_port"
export E2E_API_TARGET

echo "e2e: waiting for $E2E_API_TARGET/healthz"
attempts=60
while [ "$attempts" -gt 0 ]; do
  if curl -fsS "$E2E_API_TARGET/healthz" >/dev/null 2>&1; then
    break
  fi
  attempts=$((attempts - 1))
  sleep 2
done

if [ "$attempts" -eq 0 ]; then
  echo "e2e: the API did not answer /healthz" >&2
  compose logs --tail 50 app >&2 || true
  exit 1
fi

echo "e2e: UI on http://127.0.0.1:$E2E_UI_PORT, API on $E2E_API_TARGET"
playwright
