"""add voice reaction persistence and media metadata

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_reactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("city_id", sa.Integer(), nullable=True),
        sa.Column("reaction_tag", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reaction_tag IN ('would_compliment', 'would_wear', 'great_fit')",
            name="ck_voice_reactions_reaction_tag",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'published', 'hidden', 'deleted')",
            name="ck_voice_reactions_status",
        ),
        sa.ForeignKeyConstraint(
            ["city_id"],
            ["cities.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_voice_reactions_product_status_created_at",
        "voice_reactions",
        ["product_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_voice_reactions_user_id"),
        "voice_reactions",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "media_assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("voice_reaction_id", sa.BigInteger(), nullable=False),
        sa.Column("storage_provider", sa.String(length=30), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("extra_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms > 0",
            name="ck_media_assets_duration_positive",
        ),
        sa.CheckConstraint(
            "file_size_bytes IS NULL OR file_size_bytes >= 0",
            name="ck_media_assets_file_size_nonnegative",
        ),
        sa.CheckConstraint(
            "mime_type IN ('audio/webm', 'audio/mp4', 'audio/mpeg', 'audio/ogg')",
            name="ck_media_assets_audio_mime_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'uploaded', 'ready', 'failed', 'deleted')",
            name="ck_media_assets_status",
        ),
        sa.ForeignKeyConstraint(
            ["voice_reaction_id"],
            ["voice_reactions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "storage_provider",
            "storage_key",
            name="uq_media_assets_provider_storage_key",
        ),
        sa.UniqueConstraint("voice_reaction_id"),
    )
    op.create_index(
        "ix_media_assets_status_created_at",
        "media_assets",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("media_assets")
    op.drop_table("voice_reactions")
