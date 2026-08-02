"""add published product refresh tracking

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-07-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("last_product_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("last_link_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("last_seen_available_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column(
            "consecutive_refresh_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "products",
        sa.Column("last_refresh_status", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("last_refresh_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column(
            "needs_refresh_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        op.f("ix_products_last_refresh_status"),
        "products",
        ["last_refresh_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_products_needs_refresh_review"),
        "products",
        ["needs_refresh_review"],
        unique=False,
    )
    op.alter_column(
        "products",
        "consecutive_refresh_failures",
        server_default=None,
    )
    op.alter_column(
        "products",
        "needs_refresh_review",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_products_needs_refresh_review"),
        table_name="products",
    )
    op.drop_index(
        op.f("ix_products_last_refresh_status"),
        table_name="products",
    )
    op.drop_column("products", "needs_refresh_review")
    op.drop_column("products", "last_refresh_error")
    op.drop_column("products", "last_refresh_status")
    op.drop_column("products", "consecutive_refresh_failures")
    op.drop_column("products", "last_seen_available_at")
    op.drop_column("products", "last_link_checked_at")
    op.drop_column("products", "last_product_checked_at")
