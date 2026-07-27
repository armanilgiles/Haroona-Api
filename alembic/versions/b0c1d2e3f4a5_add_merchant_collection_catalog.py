"""add merchant collection catalog

Revision ID: b0c1d2e3f4a5
Revises: a9d0e1f2b3c4
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a9d0e1f2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchants",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("canonical_domain", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("import_batch", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_domain"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_index("ix_merchants_display_name", "merchants", ["display_name"])
    op.create_index("ix_merchants_normalized_name", "merchants", ["normalized_name"])
    op.create_index("ix_merchants_canonical_domain", "merchants", ["canonical_domain"])
    op.create_index("ix_merchants_is_active", "merchants", ["is_active"])
    op.create_index("ix_merchants_import_batch", "merchants", ["import_batch"])

    op.create_table(
        "merchant_collections",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("merchant_id", sa.String(length=64), nullable=False),
        sa.Column("collection_name", sa.String(length=255), nullable=False),
        sa.Column("collection_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.String(length=2000), nullable=False),
        sa.Column("canonical_category", sa.String(length=80), nullable=True),
        sa.Column("city_slug", sa.String(length=80), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("import_batch", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"],
            ["merchants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_url"),
    )
    op.create_index(
        "ix_merchant_collections_merchant_id",
        "merchant_collections",
        ["merchant_id"],
    )
    op.create_index(
        "ix_merchant_collections_collection_name",
        "merchant_collections",
        ["collection_name"],
    )
    op.create_index(
        "ix_merchant_collections_canonical_category",
        "merchant_collections",
        ["canonical_category"],
    )
    op.create_index(
        "ix_merchant_collections_city_slug",
        "merchant_collections",
        ["city_slug"],
    )
    op.create_index(
        "ix_merchant_collections_is_active",
        "merchant_collections",
        ["is_active"],
    )
    op.create_index(
        "ix_merchant_collections_import_batch",
        "merchant_collections",
        ["import_batch"],
    )

    op.add_column(
        "curation_scan_runs",
        sa.Column("collection_id", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_curation_scan_runs_collection_id",
        "curation_scan_runs",
        "merchant_collections",
        ["collection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_curation_scan_runs_collection_id",
        "curation_scan_runs",
        ["collection_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_curation_scan_runs_collection_id",
        table_name="curation_scan_runs",
    )
    op.drop_constraint(
        "fk_curation_scan_runs_collection_id",
        "curation_scan_runs",
        type_="foreignkey",
    )
    op.drop_column("curation_scan_runs", "collection_id")

    op.drop_index(
        "ix_merchant_collections_import_batch",
        table_name="merchant_collections",
    )
    op.drop_index(
        "ix_merchant_collections_is_active",
        table_name="merchant_collections",
    )
    op.drop_index(
        "ix_merchant_collections_city_slug",
        table_name="merchant_collections",
    )
    op.drop_index(
        "ix_merchant_collections_canonical_category",
        table_name="merchant_collections",
    )
    op.drop_index(
        "ix_merchant_collections_collection_name",
        table_name="merchant_collections",
    )
    op.drop_index(
        "ix_merchant_collections_merchant_id",
        table_name="merchant_collections",
    )
    op.drop_table("merchant_collections")

    op.drop_index("ix_merchants_import_batch", table_name="merchants")
    op.drop_index("ix_merchants_is_active", table_name="merchants")
    op.drop_index("ix_merchants_canonical_domain", table_name="merchants")
    op.drop_index("ix_merchants_normalized_name", table_name="merchants")
    op.drop_index("ix_merchants_display_name", table_name="merchants")
    op.drop_table("merchants")
