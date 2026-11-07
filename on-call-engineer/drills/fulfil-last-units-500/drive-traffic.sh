#!/bin/sh
# Order-journey traffic for drill `fulfil-last-units-500` (issue #63, T7.3).
#
# Local only. This script talks to the app the local Compose project publishes
# and refuses any host that is not a loopback address. It needs no credential
# and reads only the public `/api/stock` endpoint.
#
# What it does, per cycle, is the two-step journey the UI sends:
#   1. a normal two-line basket from the Place order screen;
#   2. for each of four low-stock SKUs, an order for *every remaining available
#      unit* (a customer buying out the rest), the Orders lane's "Fulfil order"
#      click, one retry of that click, and the cancellation the operator makes
#      when the ship keeps failing.
# Cycles are spaced so the 5m rate window holds the failures past the alert's
# 1m hold.
#
# On the drill build, the fulfil requests return `500 unexpected` (the bug) and
# the cancel returns 200. On a fixed build the same script returns 200 for every
# fulfil. The script asserts nothing and exits 0 either way; the alert list is
# the signal, not this output.
#
#   STOCKROOM_APP_URL=http://localhost:8000 sh drive-traffic.sh
#   STOCKROOM_APP_URL=http://localhost:18000 DRILL_CYCLES=2 DRILL_PAUSE_SECONDS=30 sh drive-traffic.sh
set -eu

BASE="${STOCKROOM_APP_URL:-http://localhost:8000}"
PAUSE="${DRILL_PAUSE_SECONDS:-20}"
CYCLES="${DRILL_CYCLES:-3}"

case "$BASE" in
  http://localhost:*|http://127.0.0.1:*|http://\[::1\]:*) ;;
  *)
    printf 'drive-traffic: %s is not a local endpoint; this drill never leaves localhost\n' "$BASE" >&2
    exit 2
    ;;
esac

BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT INT TERM

ORDER_ID=""
REQUESTS=0
FAILURES=0

call() { # method path [json-body] -> prints the HTTP status, body lands in $BODY
  method=$1
  path=$2
  shift 2
  if [ "$#" -gt 0 ]; then
    curl -sS --max-time 10 -o "$BODY" -w '%{http_code}' -X "$method" \
      -H 'Content-Type: application/json' --data "$1" "$BASE$path"
  else
    curl -sS --max-time 10 -o "$BODY" -w '%{http_code}' -X "$method" "$BASE$path"
  fi
}

body_field() { # name -> value from the last response document
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' \
    "$BODY" "$1"
}

available_for() { # sku -> available units, read from the live /api/stock
  call GET /api/stock >/dev/null
  python3 -c 'import json,sys
rows = json.load(open(sys.argv[1]))
print(next((row["available"] for row in rows if row["sku"] == sys.argv[2]), -1))' \
    "$BODY" "$1"
}

note() { # label status
  REQUESTS=$((REQUESTS + 1))
  case "$2" in 5*) FAILURES=$((FAILURES + 1)) ;; esac
  printf '  %-26s %s\n' "$1" "$2"
}

place() { # sku qty customer-ref -> sets ORDER_ID on 201
  payload="{\"customer_ref\":\"$3\",\"lines\":[{\"sku\":\"$1\",\"qty\":$2}]}"
  status=$(call POST /api/orders "$payload")
  note "place $1 x$2" "$status"
  if [ "$status" = "201" ]; then
    ORDER_ID=$(body_field id)
  else
    ORDER_ID=""
  fi
}

fulfil() { # order-id label
  status=$(call POST "/api/orders/$1/fulfil")
  note "fulfil $2" "$status"
}

cancel() { # order-id
  status=$(call POST "/api/orders/$1/cancel")
  note "cancel $1" "$status"
}

printf 'Driving the order journey against %s (%s cycle(s), %ss apart)\n' "$BASE" "$CYCLES" "$PAUSE"

cycle=0
while [ "$cycle" -lt "$CYCLES" ]; do
  cycle=$((cycle + 1))
  printf -- '-- cycle %s of %s\n' "$cycle" "$CYCLES"

  # A normal basket: two lines, small quantities.
  place SKU-3301 2 "DRILL-$cycle-A"
  place SKU-1042 1 "DRILL-$cycle-B"

  # A customer takes every remaining unit of a SKU; the warehouse ships it.
  for sku in SKU-8820 SKU-4410 SKU-5127 SKU-2087; do
    qty=$(available_for "$sku")
    if [ "$qty" -le 0 ]; then
      printf '  skip %s (no available units)\n' "$sku"
      continue
    fi
    place "$sku" "$qty" "DRILL-$cycle-$sku"
    if [ -z "$ORDER_ID" ]; then
      continue
    fi
    fulfil "$ORDER_ID" "$sku"
    fulfil "$ORDER_ID" "$sku retry"
    # The operator gives up on the failed ship and cancels the order.
    cancel "$ORDER_ID"
    ORDER_ID=""
  done

  if [ "$cycle" -lt "$CYCLES" ]; then
    sleep "$PAUSE"
  fi
done

printf '\nrequests on the order journey: %s, 5xx: %s\n' "$REQUESTS" "$FAILURES"
printf 'On the drill build the fulfil lines above are 500s and the cancels are 200s.\n'
printf 'Now read the alerts: curl -s localhost:9090/api/v1/alerts | python3 -m json.tool\n'
