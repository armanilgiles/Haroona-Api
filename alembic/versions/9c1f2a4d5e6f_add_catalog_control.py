"""add catalog control

Revision ID: 9c1f2a4d5e6f
Revises: 86a5861eb4db
Create Date: 2026-04-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c1f2a4d5e6f"
down_revision: Union[str, Sequence[str], None] = "86a5861eb4db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "awin_product_normalized",
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="pending"),
    )
    op.add_column(
        "awin_product_normalized",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "awin_product_normalized",
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "awin_product_normalized",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "awin_product_normalized",
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "awin_product_normalized",
        sa.Column("promoted_product_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_awin_product_normalized_review_status",
        "awin_product_normalized",
        ["review_status"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_awin_normalized_promoted_product",
        "awin_product_normalized",
        "products",
        ["promoted_product_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE awin_product_normalized
        SET review_status = CASE
            WHEN is_usable = true AND needs_review = false THEN 'approved'
            ELSE 'pending'
        END
        """
    )

    op.create_table(
        "catalog_brand_controls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("brand_key", sa.String(length=150), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("origin_country_code", sa.String(length=2), nullable=False),
        sa.Column("is_allowed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "brand_key", name="uq_catalog_brand_controls_source_key"),
    )
    op.create_index(
        "ix_catalog_brand_controls_source",
        "catalog_brand_controls",
        ["source"],
        unique=False,
    )
    op.create_index(
        "ix_catalog_brand_controls_brand_key",
        "catalog_brand_controls",
        ["brand_key"],
        unique=False,
    )

    op.add_column(
        "products",
        sa.Column("normalized_row_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_products_normalized_row_id", "products", ["normalized_row_id"], unique=False)
    op.create_foreign_key(
        "fk_products_normalized_row",
        "products",
        "awin_product_normalized",
        ["normalized_row_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE products
        SET last_seen_at = NOW()
        WHERE is_active = true
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_products_normalized_row", "products", type_="foreignkey")
    op.drop_index("ix_products_normalized_row_id", table_name="products")
    op.drop_column("products", "deactivation_reason")
    op.drop_column("products", "deactivated_at")
    op.drop_column("products", "last_seen_at")
    op.drop_column("products", "normalized_row_id")

    op.drop_index("ix_catalog_brand_controls_brand_key", table_name="catalog_brand_controls")
    op.drop_index("ix_catalog_brand_controls_source", table_name="catalog_brand_controls")
    op.drop_table("catalog_brand_controls")

    op.drop_constraint("fk_awin_normalized_promoted_product", "awin_product_normalized", type_="foreignkey")
    op.drop_index("ix_awin_product_normalized_review_status", table_name="awin_product_normalized")
    op.drop_column("awin_product_normalized", "promoted_product_id")
    op.drop_column("awin_product_normalized", "promoted_at")
    op.drop_column("awin_product_normalized", "rejection_reason")
    op.drop_column("awin_product_normalized", "reviewed_by")
    op.drop_column("awin_product_normalized", "reviewed_at")
    op.drop_column("awin_product_normalized", "review_status")