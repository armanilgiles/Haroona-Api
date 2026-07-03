"""add scan run id to product candidates

Revision ID: 3d4e5f6a7b8c
Revises: 2b7c8d9e0f11
Create Date: 2026-07-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "3d4e5f6a7b8c"
down_revision = "2b7c8d9e0f11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_candidates",
        sa.Column("scan_run_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_product_candidates_scan_run_id"),
        "product_candidates",
        ["scan_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_product_candidates_scan_run_id"), table_name="product_candidates")
    op.drop_column("product_candidates", "scan_run_id")
