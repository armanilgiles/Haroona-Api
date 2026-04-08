"""create awin normalized table

Revision ID: 86a5861eb4db
Revises: 86a31e1dea88
Create Date: 2026-04-07 18:55:42.778059

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "86a5861eb4db"
down_revision: Union[str, Sequence[str], None] = "86a31e1dea88"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "awin_product_normalized",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_product_id", sa.String(length=100), nullable=False),
        sa.Column("advertiser_id", sa.String(length=50), nullable=True),
        sa.Column("advertiser_name", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("brand_name", sa.String(length=255), nullable=True),
        sa.Column("price_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("affiliate_url", sa.Text(), nullable=True),
        sa.Column("merchant_url", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("availability", sa.String(length=50), nullable=True),
        sa.Column("google_product_category", sa.String(length=500), nullable=True),
        sa.Column("product_type", sa.String(length=500), nullable=True),
        sa.Column("normalized_category", sa.String(length=80), nullable=True),
        sa.Column("is_usable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("normalized_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["raw_id"], ["awin_product_feed_raw.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_product_id", "source", name="uq_awin_normalized_external_source"),
        sa.UniqueConstraint("raw_id"),
    )

    op.create_index(op.f("ix_awin_product_normalized_id"), "awin_product_normalized", ["id"], unique=False)
    op.create_index(op.f("ix_awin_product_normalized_raw_id"), "awin_product_normalized", ["raw_id"], unique=False)
    op.create_index(op.f("ix_awin_product_normalized_advertiser_id"), "awin_product_normalized", ["advertiser_id"], unique=False)
    op.create_index(op.f("ix_awin_product_normalized_availability"), "awin_product_normalized", ["availability"], unique=False)
    op.create_index(op.f("ix_awin_product_normalized_normalized_category"), "awin_product_normalized", ["normalized_category"], unique=False)
    op.create_index(op.f("ix_awin_product_normalized_is_usable"), "awin_product_normalized", ["is_usable"], unique=False)
    op.create_index(op.f("ix_awin_product_normalized_needs_review"), "awin_product_normalized", ["needs_review"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_awin_product_normalized_needs_review"), table_name="awin_product_normalized")
    op.drop_index(op.f("ix_awin_product_normalized_is_usable"), table_name="awin_product_normalized")
    op.drop_index(op.f("ix_awin_product_normalized_normalized_category"), table_name="awin_product_normalized")
    op.drop_index(op.f("ix_awin_product_normalized_availability"), table_name="awin_product_normalized")
    op.drop_index(op.f("ix_awin_product_normalized_advertiser_id"), table_name="awin_product_normalized")
    op.drop_index(op.f("ix_awin_product_normalized_raw_id"), table_name="awin_product_normalized")
    op.drop_index(op.f("ix_awin_product_normalized_id"), table_name="awin_product_normalized")
    op.drop_table("awin_product_normalized")