"""add Takeads affiliate-link verification state

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c9d0e1f2a3b"
down_revision: Union[str, Sequence[str], None] = "7b8c9d0e1f2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_candidates",
        sa.Column(
            "affiliate_link_status",
            sa.String(length=30),
            nullable=False,
            server_default="not_requested",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column("affiliate_sub_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("affiliate_link_error_code", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("affiliate_link_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("affiliate_link_last_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("affiliate_link_generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("affiliate_link_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("affiliate_link_verified_by", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_product_candidates_affiliate_link_status"),
        "product_candidates",
        ["affiliate_link_status"],
    )
    op.create_index(
        "uq_product_candidates_affiliate_sub_id",
        "product_candidates",
        ["affiliate_sub_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_product_candidates_affiliate_sub_id",
        table_name="product_candidates",
    )
    op.drop_index(
        op.f("ix_product_candidates_affiliate_link_status"),
        table_name="product_candidates",
    )
    op.drop_column("product_candidates", "affiliate_link_verified_by")
    op.drop_column("product_candidates", "affiliate_link_verified_at")
    op.drop_column("product_candidates", "affiliate_link_generated_at")
    op.drop_column("product_candidates", "affiliate_link_last_attempted_at")
    op.drop_column("product_candidates", "affiliate_link_error_message")
    op.drop_column("product_candidates", "affiliate_link_error_code")
    op.drop_column("product_candidates", "affiliate_sub_id")
    op.drop_column("product_candidates", "affiliate_link_status")
