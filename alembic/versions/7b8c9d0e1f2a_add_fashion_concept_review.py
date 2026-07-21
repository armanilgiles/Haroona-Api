"""add fashion concept review

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b8c9d0e1f2a"
down_revision: Union[str, Sequence[str], None] = "6a7b8c9d0e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fashion_concepts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("traits", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concept_id"),
    )
    op.create_index(op.f("ix_fashion_concepts_id"), "fashion_concepts", ["id"])
    op.create_index(op.f("ix_fashion_concepts_concept_id"), "fashion_concepts", ["concept_id"], unique=True)
    op.create_index(op.f("ix_fashion_concepts_category"), "fashion_concepts", ["category"])
    op.create_index(op.f("ix_fashion_concepts_active"), "fashion_concepts", ["active"])

    op.create_table(
        "fashion_concept_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("normalized_phrase", sa.String(length=255), nullable=False),
        sa.Column("display_phrase", sa.String(length=255), nullable=False),
        sa.Column("concept_id", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_phrase"),
    )
    op.create_index(op.f("ix_fashion_concept_aliases_id"), "fashion_concept_aliases", ["id"])
    op.create_index(op.f("ix_fashion_concept_aliases_normalized_phrase"), "fashion_concept_aliases", ["normalized_phrase"], unique=True)
    op.create_index(op.f("ix_fashion_concept_aliases_concept_id"), "fashion_concept_aliases", ["concept_id"])
    op.create_index(op.f("ix_fashion_concept_aliases_active"), "fashion_concept_aliases", ["active"])

    op.create_table(
        "fashion_concept_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("normalized_phrase", sa.String(length=255), nullable=False),
        sa.Column("display_phrase", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("examples", sa.JSON(), nullable=False),
        sa.Column("candidate_keys", sa.JSON(), nullable=False),
        sa.Column("resolved_concept_id", sa.String(length=120), nullable=True),
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_phrase"),
    )
    op.create_index(op.f("ix_fashion_concept_proposals_id"), "fashion_concept_proposals", ["id"])
    op.create_index(op.f("ix_fashion_concept_proposals_normalized_phrase"), "fashion_concept_proposals", ["normalized_phrase"], unique=True)
    op.create_index(op.f("ix_fashion_concept_proposals_status"), "fashion_concept_proposals", ["status"])
    op.create_index(op.f("ix_fashion_concept_proposals_resolved_concept_id"), "fashion_concept_proposals", ["resolved_concept_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_fashion_concept_proposals_resolved_concept_id"), table_name="fashion_concept_proposals")
    op.drop_index(op.f("ix_fashion_concept_proposals_status"), table_name="fashion_concept_proposals")
    op.drop_index(op.f("ix_fashion_concept_proposals_normalized_phrase"), table_name="fashion_concept_proposals")
    op.drop_index(op.f("ix_fashion_concept_proposals_id"), table_name="fashion_concept_proposals")
    op.drop_table("fashion_concept_proposals")

    op.drop_index(op.f("ix_fashion_concept_aliases_active"), table_name="fashion_concept_aliases")
    op.drop_index(op.f("ix_fashion_concept_aliases_concept_id"), table_name="fashion_concept_aliases")
    op.drop_index(op.f("ix_fashion_concept_aliases_normalized_phrase"), table_name="fashion_concept_aliases")
    op.drop_index(op.f("ix_fashion_concept_aliases_id"), table_name="fashion_concept_aliases")
    op.drop_table("fashion_concept_aliases")

    op.drop_index(op.f("ix_fashion_concepts_active"), table_name="fashion_concepts")
    op.drop_index(op.f("ix_fashion_concepts_category"), table_name="fashion_concepts")
    op.drop_index(op.f("ix_fashion_concepts_concept_id"), table_name="fashion_concepts")
    op.drop_index(op.f("ix_fashion_concepts_id"), table_name="fashion_concepts")
    op.drop_table("fashion_concepts")
