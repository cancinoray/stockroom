# Domain Model

How the correctness core is implemented. Behaviour is defined in
[product-spec.md](../product-spec.md); this document covers schema, locking and the invariants as
executable checks.

## 1. Principle: ledger first, caches second

`stock.on_hand` and `stock.reserved` are denormalised counters, kept for hot-path reads. The
`movements` table is the source of truth. Every counter change is accompanied by exactly one
movement row in the same transaction, so the counters are always *derivable* and drift is
*detectable*. This is the arrangement that makes "why does the sheet say 7?" answerable.

## 2. Schema

```
products
  id                uuid pk
  sku               text unique not null        -- human-readable, e.g. SKU-1042
  name              text not null
  unit_price_cents  integer not null check (unit_price_cents >= 0)
  reorder_point     integer not null default 0  -- low-stock threshold on available
  active            boolean not null default true
  created_at        timestamptz not null default now()

warehouses
  id    uuid pk
  code  text unique not null                    -- one seeded row: 'MAIN'

stock
  warehouse_id  uuid not null references warehouses(id)
  sku           text not null references products(sku)
  on_hand       integer not null default 0 check (on_hand >= 0)
  reserved      integer not null default 0 check (reserved >= 0)
  updated_at    timestamptz not null default now()
  primary key (warehouse_id, sku)
  check (reserved <= on_hand)                   -- I1 enforced by the database, not only by code

movements                                        -- append-only ledger
  id               uuid pk
  warehouse_id     uuid not null references warehouses(id)
  sku              text not null references products(sku)
  delta_on_hand    integer not null default 0
  delta_reserved   integer not null default 0
  reason           text not null check (reason in ('receive','adjust','reserve','release','ship'))
  order_id         uuid null references orders(id)
  actor            text not null                -- operator name, from config
  note             text null
  created_at       timestamptz not null default now()
  index on (warehouse_id, sku, created_at desc)

orders
  id            uuid pk
  warehouse_id  uuid not null references warehouses(id)
  customer_ref  text not null check (char_length(customer_ref) between 3 and 40)
  status        text not null check (status in ('confirmed','cancelled','fulfilled'))
  created_at    timestamptz not null default now()
  -- stretch S1: idempotency_key text unique

order_lines
  id                uuid pk
  order_id          uuid not null references orders(id) on delete restrict
  sku               text not null references products(sku)
  qty               integer not null check (qty > 0)
  unit_price_cents  integer not null            -- snapshot at order time
  unique (order_id, sku)                          -- one line per SKU keeps reservation simple
```

Two deliberate choices:

- **`unique (order_id, sku)`.** Merging duplicate lines at the API boundary removes a whole class
  of "reserved twice, released once" bugs. The frontend aggregates quantities per SKU.
- **`check (reserved <= on_hand)`.** The database rejects the state, so a bug in application
  logic becomes a failed transaction rather than silent corruption. Tests assert that this
  constraint actually fires.

### Ledger semantics

| reason | `delta_on_hand` | `delta_reserved` | Written by |
| --- | --- | --- | --- |
| `receive` | `+qty` | `0` | `POST /api/stock/receive` |
| `adjust` | `±delta` | `0` | `POST /api/stock/adjust` |
| `reserve` | `0` | `+qty` | `POST /api/orders` |
| `release` | `0` | `-qty` | `POST /api/orders/{id}/cancel` |
| `ship` | `-qty` | `-qty` | `POST /api/orders/{id}/fulfil` |

Because both counters are sums of the same ledger, invariant checks are two `SUM`s, and
`available = on_hand - reserved` is always meaningful.

### Append-only enforcement

A `BEFORE UPDATE OR DELETE` trigger on `movements` raises an exception. In production the
application role is granted `INSERT` and `SELECT` on that table only. Two mechanisms, because the
rule matters more than the convenience of a test fixture — tests that need a corrupt row create
one with a dedicated `admin` role, which is itself a test of the guard.

## 3. Reservation transaction

The only place stock is written. Pseudocode, then the reasoning:

```sql
BEGIN;

-- 1. Lock every stock row this order touches, in ascending SKU order.
SELECT sku, on_hand, reserved
  FROM stock
 WHERE warehouse_id = :wh AND sku = ANY(:skus)
 ORDER BY sku
   FOR UPDATE;

-- 2. Validate all lines against fresh values while holding the locks.
--    If any line has (on_hand - reserved) < qty -> ROLLBACK, return 409 insufficient_stock.

-- 3. Insert order, lines, and one 'reserve' movement per line.
-- 4. Update the cached counters.
UPDATE stock SET reserved = reserved + v.qty, updated_at = now()
  FROM (VALUES (:sku1, :q1), (:sku2, :q2)) AS v(sku, qty)
 WHERE stock.warehouse_id = :wh AND stock.sku = v.sku;

COMMIT;
```

**Why `FOR UPDATE` with `ORDER BY sku`.** Lock acquisition order is the only thing that prevents
deadlocks between two multi-line orders that touch the same SKUs in a different order. Sorting
first means every transaction walks the same sequence, so no wait-for cycle can form.

**Why not a conditional `UPDATE ... WHERE on_hand - reserved >= :q` per line.** It is atomic per
SKU and needs no explicit lock, but across several lines it turns all-or-nothing into
"update, watch a count, roll back" with the failure expressed as an exception per line. Two
statements that mean "validate" and "write" are easier to test, easier to read in a trace, and
produce a precise per-line `409` body. The conditional-update version is the fallback if profiling
ever shows the lock hold is too wide — not the starting point.

**Deadlock handling.** Ordered locking makes deadlocks structurally impossible for this workload.
A retry-once wrapper on `SerializationFailure` remains as defence in depth, and the test suite
asserts that no request under contention ever returns `500`.

**Isolation level.** `READ COMMITTED` (Postgres default) is sufficient because all validation reads
happen after the rows are locked.

## 4. Invariants as executable checks

`GET /api/invariants` runs these and never returns `500` — a broken check that crashes is worse
than no check.

```sql
-- I2 / I3: caches must equal the ledger, per SKU
SELECT s.sku,
       s.on_hand            AS cached_on_hand,
       COALESCE(SUM(m.delta_on_hand), 0)  AS ledger_on_hand,
       s.reserved           AS cached_reserved,
       COALESCE(SUM(m.delta_reserved), 0) AS ledger_reserved
  FROM stock s
  LEFT JOIN movements m USING (warehouse_id, sku)
 GROUP BY s.warehouse_id, s.sku, s.on_hand, s.reserved
HAVING s.on_hand  <> COALESCE(SUM(m.delta_on_hand), 0)
    OR s.reserved <> COALESCE(SUM(m.delta_reserved), 0)
    OR s.reserved > s.on_hand
    OR s.on_hand < 0
    OR s.reserved < 0;
```

```sql
-- I5: confirmed orders hold exactly one reservation per line, of the right size
SELECT o.id, l.sku, l.qty, COALESCE(SUM(m.delta_reserved), 0) AS reserved
  FROM orders o
  JOIN order_lines l ON l.order_id = o.id
  LEFT JOIN movements m
         ON m.order_id = o.id AND m.sku = l.sku AND m.reason = 'reserve'
 WHERE o.status = 'confirmed'
 GROUP BY o.id, l.sku, l.qty
HAVING COALESCE(SUM(m.delta_reserved), 0) <> l.qty;
```

The endpoint reports rule id, SKU, and the two disagreeing numbers — enough to act on, nothing
that leaks customer data. Alert `InventoryInvariantViolation` fires when the violation count is
above zero (see `observability/alerts.yaml`).

## 5. Testing the concurrency claim

The claim in `US2` is only credible if the test cannot be serialised by the harness.

- **Harness:** `ThreadPoolExecutor(max_workers=20)` + `threading.Barrier(20)`, so all requests are
  released at the same instant, hitting a live `uvicorn` on an ephemeral port — not `TestClient`,
  which is synchronous and would fake the result.
- **Assertion:** exactly one `201`, nineteen `409`, `reserved == 1`, `available == 0`,
  `/api/invariants` clean, no `500`.
- **Repeat:** 50 iterations of the same scenario to catch flakiness, plus a two-SKU variant with
  opposing line order to exercise the deadlock-prevention claim.
- **Why a live server:** an in-process test can accidentally serialise at the ASGI layer and pass
  while production fails. If the test cannot fail, it proves nothing.

## 6. Migrations and seed

- Alembic, one migration per task, generated then hand-reviewed (autogenerate misses triggers and
  check constraints).
- `make migrate` runs `alembic upgrade head`; the container entrypoint runs it before the app
  starts, so a deploy cannot serve a stale schema.
- `make seed` is idempotent: one warehouse `MAIN`, 8 products with reorder points, opening
  `receive` movements. Seeded data is demo data and contains no real customers.
