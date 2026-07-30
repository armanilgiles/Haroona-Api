"""add automatic city recommendation and assignment metadata

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "curation_scan_runs",
        sa.Column(
            "city_mode",
            sa.String(length=20),
            nullable=False,
            server_default="selected",
        ),
    )
    op.create_index(
        "ix_curation_scan_runs_city_mode",
        "curation_scan_runs",
        ["city_mode"],
    )
    op.alter_column(
        "curation_scan_runs",
        "target_city_slug",
        existing_type=sa.String(length=80),
        nullable=True,
    )

    op.add_column(
        "product_candidates",
        sa.Column(
            "city_scan_mode",
            sa.String(length=20),
            nullable=False,
            server_default="selected",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column("recommended_city_slug", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("recommended_city_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("runner_up_city_slug", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("runner_up_city_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("city_score_margin", sa.Integer(), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "city_assignment_status",
            sa.String(length=40),
            nullable=False,
            server_default="manually_assigned",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "city_assignment_source",
            sa.String(length=40),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "city_candidates",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "manual_city_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column("city_assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("city_assigned_by", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_product_candidates_city_scan_mode",
        "product_candidates",
        ["city_scan_mode"],
    )
    op.create_index(
        "ix_product_candidates_recommended_city_slug",
        "product_candidates",
        ["recommended_city_slug"],
    )
    op.create_index(
        "ix_product_candidates_city_assignment_status",
        "product_candidates",
        ["city_assignment_status"],
    )

    # Existing records retain their final city and are classified as legacy
    # curator-selected assignments. No published product is detached.
    op.execute(
        """
        UPDATE product_candidates
        SET recommended_city_slug = target_city_slug,
            recommended_city_score = haroona_score,
            city_score_margin = 0,
            city_assigned_at = COALESCE(reviewed_at, created_at),
            city_assigned_by = COALESCE(reviewed_by, 'legacy')
        WHERE target_city_slug IS NOT NULL
        """
    )
    op.alter_column(
        "product_candidates",
        "target_city_slug",
        existing_type=sa.String(length=80),
        nullable=True,
    )


def downgrade() -> None:
    # Older application versions require a city on every candidate and scan.
    op.execute(
        """
        UPDATE product_candidates
        SET target_city_slug = COALESCE(recommended_city_slug, 'london')
        WHERE target_city_slug IS NULL
        """
    )
    op.execute(
        """
        UPDATE curation_scan_runs
        SET target_city_slug = COALESCE(target_city_slug, 'london')
        WHERE target_city_slug IS NULL
        """
    )
    op.alter_column(
        "product_candidates",
        "target_city_slug",
        existing_type=sa.String(length=80),
        nullable=False,
    )
    op.alter_column(
        "curation_scan_runs",
        "target_city_slug",
        existing_type=sa.String(length=80),
        nullable=False,
    )

    op.drop_index(
        "ix_product_candidates_city_assignment_status",
        table_name="product_candidates",
    )
    op.drop_index(
        "ix_product_candidates_recommended_city_slug",
        table_name="product_candidates",
    )
    op.drop_index(
        "ix_product_candidates_city_scan_mode",
        table_name="product_candidates",
    )
    op.drop_column("product_candidates", "city_assigned_by")
    op.drop_column("product_candidates", "city_assigned_at")
    op.drop_column("product_candidates", "manual_city_override")
    op.drop_column("product_candidates", "city_candidates")
    op.drop_column("product_candidates", "city_assignment_source")
    op.drop_column("product_candidates", "city_assignment_status")
    op.drop_column("product_candidates", "city_score_margin")
    op.drop_column("product_candidates", "runner_up_city_score")
    op.drop_column("product_candidates", "runner_up_city_slug")
    op.drop_column("product_candidates", "recommended_city_score")
    op.drop_column("product_candidates", "recommended_city_slug")
    op.drop_column("product_candidates", "city_scan_mode")

    op.drop_index(
        "ix_curation_scan_runs_city_mode",
        table_name="curation_scan_runs",
    )
    op.drop_column("curation_scan_runs", "city_mode")
