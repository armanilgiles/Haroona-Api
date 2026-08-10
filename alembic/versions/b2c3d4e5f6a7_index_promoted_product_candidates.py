"""index promoted product candidates used by product detail

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-10
"""
from __future__ import annotations

from alembic import op


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    options = {
        "index_name": "ix_product_candidates_promoted_product_id",
        "table_name": "product_candidates",
        "columns": ["promoted_product_id"],
        "unique": False,
    }
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.create_index(**options, postgresql_concurrently=True)
        return
    op.create_index(**options)


def downgrade() -> None:
    options = {
        "index_name": "ix_product_candidates_promoted_product_id",
        "table_name": "product_candidates",
    }
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(**options, postgresql_concurrently=True)
        return
    op.drop_index(**options)
