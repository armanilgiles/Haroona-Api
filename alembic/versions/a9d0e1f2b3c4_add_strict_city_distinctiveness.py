"""add strict city distinctiveness settings and analysis

Revision ID: a9d0e1f2b3c4
Revises: 8c9d0e1f2a3b
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9d0e1f2b3c4"
down_revision: Union[str, Sequence[str], None] = "8c9d0e1f2a3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "curation_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "scoring_mode",
            sa.String(length=40),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "scoring_analysis",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "manual_observed_garment_details",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )

    # Existing and published candidates retain their original scores. The new
    # columns only describe those rows as legacy until an explicit rescore.
    op.alter_column("product_candidates", "scoring_mode", server_default=None)
    op.alter_column("product_candidates", "scoring_analysis", server_default=None)
    op.alter_column(
        "product_candidates",
        "manual_observed_garment_details",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("product_candidates", "manual_observed_garment_details")
    op.drop_column("product_candidates", "scoring_analysis")
    op.drop_column("product_candidates", "scoring_mode")
    op.drop_table("curation_settings")
