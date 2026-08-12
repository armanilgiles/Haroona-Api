"""add voice reaction reporting and moderation queue

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_reaction_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("voice_reaction_id", sa.BigInteger(), nullable=False),
        sa.Column("reporter_user_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("details", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resolved_by_user_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('harassment', 'hate', 'sexual', 'spam', 'privacy', 'off_topic', 'other')",
            name="ck_voice_reaction_reports_reason",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')",
            name="ck_voice_reaction_reports_status",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["voice_reaction_id"],
            ["voice_reactions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "voice_reaction_id",
            "reporter_user_id",
            name="uq_voice_reaction_reports_reaction_reporter",
        ),
    )
    op.create_index(
        "ix_voice_reaction_reports_status_created_at",
        "voice_reaction_reports",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_voice_reaction_reports_reaction_status",
        "voice_reaction_reports",
        ["voice_reaction_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_voice_reaction_reports_reaction_status",
        table_name="voice_reaction_reports",
    )
    op.drop_index(
        "ix_voice_reaction_reports_status_created_at",
        table_name="voice_reaction_reports",
    )
    op.drop_table("voice_reaction_reports")
