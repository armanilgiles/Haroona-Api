"""add voice reaction experience and compliment response

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("voice_reactions") as batch_op:
        batch_op.add_column(
            sa.Column("experience_type", sa.String(length=30), nullable=True)
        )
        batch_op.add_column(
            sa.Column("compliment_response", sa.String(length=20), nullable=True)
        )
        batch_op.drop_constraint(
            "ck_voice_reactions_reaction_tag",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_voice_reactions_reaction_tag",
            "reaction_tag IN ('general', 'would_compliment', 'would_wear', "
            "'great_fit', 'great_city_fit', 'got_compliments', 'loved_fit', "
            "'would_wear_again')",
        )
        batch_op.create_check_constraint(
            "ck_voice_reactions_experience_type",
            "experience_type IS NULL OR "
            "experience_type IN ('first_impression', 'wore_it')",
        )
        batch_op.create_check_constraint(
            "ck_voice_reactions_compliment_response",
            "compliment_response IS NULL OR "
            "compliment_response IN ('yes', 'no', 'not_sure')",
        )
        batch_op.create_check_constraint(
            "ck_voice_reactions_compliment_requires_experience",
            "compliment_response IS NULL OR experience_type IS NOT NULL",
        )
        batch_op.create_check_constraint(
            "ck_voice_reactions_compliment_matches_experience",
            "compliment_response IS NULL OR "
            "(experience_type = 'first_impression' AND "
            "compliment_response IN ('yes', 'no', 'not_sure')) OR "
            "(experience_type = 'wore_it' AND "
            "compliment_response IN ('yes', 'no'))",
        )


def downgrade() -> None:
    with op.batch_alter_table("voice_reactions") as batch_op:
        batch_op.drop_constraint(
            "ck_voice_reactions_compliment_matches_experience",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_voice_reactions_compliment_requires_experience",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_voice_reactions_compliment_response",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_voice_reactions_experience_type",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_voice_reactions_reaction_tag",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_voice_reactions_reaction_tag",
            "reaction_tag IN ('would_compliment', 'would_wear', 'great_fit')",
        )
        batch_op.drop_column("compliment_response")
        batch_op.drop_column("experience_type")
