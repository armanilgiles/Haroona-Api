"""add optimized product image fields

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "4e5f6a7b8c9d"
down_revision = "3d4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("optimized_product_image_url", sa.String(length=800), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("product_image_width", sa.Integer(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("product_image_height", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "product_image_height")
    op.drop_column("products", "product_image_width")
    op.drop_column("products", "optimized_product_image_url")
