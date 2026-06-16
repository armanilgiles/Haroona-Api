"""create product candidates

Revision ID: 2b7c8d9e0f11
Revises: 1f2e3d4c5b6a
Create Date: 2026-06-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "2b7c8d9e0f11"
down_revision = "1f2e3d4c5b6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="collection"),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("merchant_name", sa.String(length=255), nullable=False),
        sa.Column("brand_name", sa.String(length=255), nullable=True),
        sa.Column("external_product_id", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("affiliate_url", sa.Text(), nullable=True),
        sa.Column("merchant_url", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("availability", sa.String(length=50), nullable=True),
        sa.Column("normalized_category", sa.String(length=80), nullable=True),
        sa.Column("target_city_slug", sa.String(length=80), nullable=False),
        sa.Column("city_connection_type", sa.String(length=40), nullable=True),
        sa.Column("city_connection_note", sa.String(length=255), nullable=True),
        sa.Column("haroona_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_product_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["promoted_product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_product_id", name="uq_product_candidates_source_external"),
    )
    op.create_index(op.f("ix_product_candidates_id"), "product_candidates", ["id"], unique=False)
    op.create_index(op.f("ix_product_candidates_source"), "product_candidates", ["source"], unique=False)
    op.create_index(op.f("ix_product_candidates_merchant_name"), "product_candidates", ["merchant_name"], unique=False)
    op.create_index(op.f("ix_product_candidates_availability"), "product_candidates", ["availability"], unique=False)
    op.create_index(op.f("ix_product_candidates_normalized_category"), "product_candidates", ["normalized_category"], unique=False)
    op.create_index(op.f("ix_product_candidates_target_city_slug"), "product_candidates", ["target_city_slug"], unique=False)
    op.create_index(op.f("ix_product_candidates_haroona_score"), "product_candidates", ["haroona_score"], unique=False)
    op.create_index(op.f("ix_product_candidates_review_status"), "product_candidates", ["review_status"], unique=False)
    op.create_index(op.f("ix_product_candidates_created_at"), "product_candidates", ["created_at"], unique=False)

    op.alter_column("product_candidates", "source_type", server_default=None)
    op.alter_column("product_candidates", "haroona_score", server_default=None)
    op.alter_column("product_candidates", "review_status", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_product_candidates_created_at"), table_name="product_candidates")
    op.drop_index(op.f("ix_product_candidates_review_status"), table_name="product_candidates")
    op.drop_index(op.f("ix_product_candidates_haroona_score"), table_name="product_candidates")
    op.drop_index(op.f("ix_product_candidates_target_city_slug"), table_name="product_candidates")
    op.drop_index(op.f("ix_product_candidates_normalized_category"), table_name="product_candidates")
    op.drop_index(op.f("ix_product_candidates_availability"), table_name="product_candidates")
    op.drop_index(op.f("ix_product_candidates_merchant_name"), table_name="product_candidates")
    op.drop_index(op.f("ix_product_candidates_source"), table_name="product_candidates")
    op.drop_index(op.f("ix_product_candidates_id"), table_name="product_candidates")
    op.drop_table("product_candidates")
