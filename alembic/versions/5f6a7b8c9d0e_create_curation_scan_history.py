"""create curation scan history

Revision ID: 5f6a7b8c9d0e
Revises: 4e5f6a7b8c9d
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "5f6a7b8c9d0e"
down_revision = "4e5f6a7b8c9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curation_scan_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_host", sa.String(length=255), nullable=True),
        sa.Column("merchant_name", sa.String(length=255), nullable=False),
        sa.Column("target_city_slug", sa.String(length=80), nullable=False),
        sa.Column("normalized_category", sa.String(length=80), nullable=True),
        sa.Column("scanner_name", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=True),
        sa.Column("merchant_verification", sa.String(length=20), nullable=True),
        sa.Column("requested_image_mode", sa.String(length=30), nullable=False),
        sa.Column("effective_image_mode", sa.String(length=30), nullable=True),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("saved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_curation_scan_runs_status"),
        "curation_scan_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_curation_scan_runs_source_host"),
        "curation_scan_runs",
        ["source_host"],
        unique=False,
    )
    op.create_index(
        op.f("ix_curation_scan_runs_merchant_name"),
        "curation_scan_runs",
        ["merchant_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_curation_scan_runs_target_city_slug"),
        "curation_scan_runs",
        ["target_city_slug"],
        unique=False,
    )
    op.create_index(
        op.f("ix_curation_scan_runs_started_at"),
        "curation_scan_runs",
        ["started_at"],
        unique=False,
    )

    op.create_table(
        "curation_scan_run_candidates",
        sa.Column("scan_run_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["product_candidates.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scan_run_id"],
            ["curation_scan_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("scan_run_id", "candidate_id"),
    )
    op.create_index(
        op.f("ix_curation_scan_run_candidates_candidate_id"),
        "curation_scan_run_candidates",
        ["candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_curation_scan_run_candidates_candidate_id"),
        table_name="curation_scan_run_candidates",
    )
    op.drop_table("curation_scan_run_candidates")
    op.drop_index(op.f("ix_curation_scan_runs_started_at"), table_name="curation_scan_runs")
    op.drop_index(
        op.f("ix_curation_scan_runs_target_city_slug"),
        table_name="curation_scan_runs",
    )
    op.drop_index(
        op.f("ix_curation_scan_runs_merchant_name"),
        table_name="curation_scan_runs",
    )
    op.drop_index(op.f("ix_curation_scan_runs_source_host"), table_name="curation_scan_runs")
    op.drop_index(op.f("ix_curation_scan_runs_status"), table_name="curation_scan_runs")
    op.drop_table("curation_scan_runs")
