"""schema, constraints and the append-only movements trigger

Hand-reviewed against ``_docs/domain.md`` §2. Autogenerate does not emit the
check constraints, the descending index or the trigger, so they are written
out explicitly.

Revision ID: 0001_schema_constraints
Revises:
Create Date: 2026-10-31

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_schema_constraints"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("reorder_point", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
        sa.CheckConstraint(
            "unit_price_cents >= 0",
            name="ck_products_unit_price_cents_non_negative",
        ),
    )

    op.create_table(
        "warehouses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_warehouses_code"),
    )

    op.create_table(
        "orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "char_length(customer_ref) between 3 and 40",
            name="ck_orders_customer_ref_length",
        ),
        sa.CheckConstraint(
            "status in ('confirmed', 'cancelled', 'fulfilled')",
            name="ck_orders_status",
        ),
    )

    op.create_table(
        "stock",
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("on_hand", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reserved", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["sku"], ["products.sku"]),
        sa.PrimaryKeyConstraint("warehouse_id", "sku"),
        sa.CheckConstraint("on_hand >= 0", name="ck_stock_on_hand_non_negative"),
        sa.CheckConstraint("reserved >= 0", name="ck_stock_reserved_non_negative"),
        sa.CheckConstraint("reserved <= on_hand", name="ck_stock_reserved_le_on_hand"),
    )

    op.create_table(
        "order_lines",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sku"], ["products.sku"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "sku", name="uq_order_lines_order_id_sku"),
        sa.CheckConstraint("qty > 0", name="ck_order_lines_qty_positive"),
    )

    op.create_table(
        "movements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("delta_on_hand", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("delta_reserved", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.ForeignKeyConstraint(["sku"], ["products.sku"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "reason in ('receive', 'adjust', 'reserve', 'release', 'ship')",
            name="ck_movements_reason",
        ),
    )

    op.execute(
        "CREATE INDEX ix_movements_warehouse_id_sku_created_at "
        "ON movements (warehouse_id, sku, created_at DESC)"
    )

    op.execute(
        """
        CREATE FUNCTION movements_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'movements are append-only: % is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER movements_append_only
        BEFORE UPDATE OR DELETE ON movements
        FOR EACH ROW EXECUTE FUNCTION movements_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS movements_append_only ON movements")
    op.execute("DROP INDEX IF EXISTS ix_movements_warehouse_id_sku_created_at")
    op.drop_table("movements")
    op.execute("DROP FUNCTION IF EXISTS movements_append_only()")
    op.drop_table("order_lines")
    op.drop_table("stock")
    op.drop_table("orders")
    op.drop_table("products")
    op.drop_table("warehouses")
