"""add product price refresh metadata

Revision ID: 1f2e3d4c5b6a
Revises: a7b4c9d2e8f1
Create Date: 2026-05-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "1f2e3d4c5b6a"
down_revision = "a7b4c9d2e8f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("regular_price", sa.Numeric(10, 2), nullable=True))
    op.add_column(
        "products",
        sa.Column(
            "availability_status",
            sa.String(length=50),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column("products", sa.Column("last_price_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("products", sa.Column("price_check_status", sa.String(length=30), nullable=True))
    op.add_column("products", sa.Column("price_check_error", sa.Text(), nullable=True))

    op.create_table(
        "product_price_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("old_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("new_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("old_regular_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("new_regular_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("old_availability_status", sa.String(length=50), nullable=True),
        sa.Column("new_availability_status", sa.String(length=50), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_product_price_snapshots_id"), "product_price_snapshots", ["id"], unique=False)
    op.create_index(op.f("ix_product_price_snapshots_product_id"), "product_price_snapshots", ["product_id"], unique=False)
    op.create_index(op.f("ix_product_price_snapshots_source"), "product_price_snapshots", ["source"], unique=False)
    op.create_index(op.f("ix_product_price_snapshots_external_id"), "product_price_snapshots", ["external_id"], unique=False)
    op.create_index(op.f("ix_product_price_snapshots_checked_at"), "product_price_snapshots", ["checked_at"], unique=False)

    op.alter_column("products", "availability_status", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_product_price_snapshots_checked_at"), table_name="product_price_snapshots")
    op.drop_index(op.f("ix_product_price_snapshots_external_id"), table_name="product_price_snapshots")
    op.drop_index(op.f("ix_product_price_snapshots_source"), table_name="product_price_snapshots")
    op.drop_index(op.f("ix_product_price_snapshots_product_id"), table_name="product_price_snapshots")
    op.drop_index(op.f("ix_product_price_snapshots_id"), table_name="product_price_snapshots")
    op.drop_table("product_price_snapshots")

    op.drop_column("products", "price_check_error")
    op.drop_column("products", "price_check_status")
    op.drop_column("products", "last_price_checked_at")
    op.drop_column("products", "availability_status")
    op.drop_column("products", "regular_price")
