"""add consumer search indexes

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
Create Date: 2026-08-09
"""
from __future__ import annotations

from alembic import op


revision = "a1b2c3d4e5f6"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


CURATED_PRODUCT_PREDICATE = (
    "is_active IS TRUE "
    "AND city_id IS NOT NULL "
    "AND (normalized_row_id IS NOT NULL OR source = 'shopify')"
)


def upgrade() -> None:
    # pg_trgm supports the existing case-insensitive substring behavior without
    # introducing a separate search service or a denormalized search table.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_search_name_trgm "
        "ON products USING gin (lower(name) gin_trgm_ops) "
        f"WHERE {CURATED_PRODUCT_PREDICATE}"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_brands_search_name_trgm "
        "ON brands USING gin (lower(name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cities_search_name_trgm "
        "ON cities USING gin (lower(name) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_curated_brand_id "
        "ON products (brand_id) "
        f"WHERE {CURATED_PRODUCT_PREDICATE}"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_curated_city_id "
        "ON products (city_id) "
        f"WHERE {CURATED_PRODUCT_PREDICATE}"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_curated_city_id")
    op.execute("DROP INDEX IF EXISTS ix_products_curated_brand_id")
    op.execute("DROP INDEX IF EXISTS ix_cities_search_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_brands_search_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_search_name_trgm")

    # The extension may be shared by other database objects, so downgrade does
    # not remove it.
