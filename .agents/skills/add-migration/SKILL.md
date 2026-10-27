---
name: add-migration
description: Add a safe Alembic migration for a Stockroom schema change, including check constraints, indexes and the append-only trigger.
---

# Add a migration

Use this whenever the schema changes. Never edit a migration that has already been applied
anywhere.

1. Confirm the change belongs in this task. A schema change inside a UI task is scope creep.
2. Create the revision and tell Alembic to autogenerate a first draft.
3. **Hand-review the draft.** Autogenerate misses what this schema depends on:
   - `check (on_hand >= 0)`, `check (reserved >= 0)`, `check (reserved <= on_hand)`
   - `unique (order_id, sku)` on order lines
   - the `BEFORE UPDATE OR DELETE` trigger on `movements`
   - indexes: `(warehouse_id, sku, created_at desc)` on movements
4. Test it three ways on a scratch database: `upgrade head` on empty, `downgrade -1`, then
   `upgrade head` again. A migration that cannot be reversed is a migration that cannot be
   rolled back during an incident.
5. Run `make test-integration` — the suite creates its schema from migrations, so a broken
   migration fails there first.
6. Update [_docs/domain.md](../../../_docs/domain.md) §2 if the schema changed.
7. If the migration rewrites data, say so in the PR and note the expected duration.

Prove it: `make migrate && make reset && make test-integration`, expected: all green.
