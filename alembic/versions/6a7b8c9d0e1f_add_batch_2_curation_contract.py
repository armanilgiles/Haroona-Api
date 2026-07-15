"""add batch 2 curation contract

Revision ID: 6a7b8c9d0e1f
Revises: 5f6a7b8c9d0e
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a7b8c9d0e1f"
down_revision: Union[str, Sequence[str], None] = "5f6a7b8c9d0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_candidates",
        sa.Column(
            "merchant_verification",
            sa.String(length=20),
            nullable=False,
            server_default="unverified",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column("merchant_profile_key", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "eligibility_status",
            sa.String(length=20),
            nullable=False,
            server_default="needs_review",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "eligibility_reasons",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column("platform_alignment_score", sa.Numeric(3, 1), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "platform_alignment_reasons",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "city_fit_score",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "city_fit_scores",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column("secondary_city_slug", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("scoring_confidence", sa.Integer(), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "scoring_method",
            sa.String(length=40),
            nullable=False,
            server_default="deterministic_rules",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "scoring_version",
            sa.String(length=40),
            nullable=False,
            server_default="rules_v1",
        ),
    )

    op.execute(
        "UPDATE product_candidates SET city_fit_score = haroona_score, "
        "city_fit_scores = json_build_object(target_city_slug, haroona_score)"
    )

    op.create_index(
        op.f("ix_product_candidates_eligibility_status"),
        "product_candidates",
        ["eligibility_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_candidates_city_fit_score"),
        "product_candidates",
        ["city_fit_score"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_candidates_secondary_city_slug"),
        "product_candidates",
        ["secondary_city_slug"],
        unique=False,
    )

    for column in (
        "merchant_verification",
        "eligibility_status",
        "eligibility_reasons",
        "platform_alignment_reasons",
        "city_fit_score",
        "city_fit_scores",
        "scoring_method",
        "scoring_version",
    ):
        op.alter_column("product_candidates", column, server_default=None)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_product_candidates_secondary_city_slug"),
        table_name="product_candidates",
    )
    op.drop_index(
        op.f("ix_product_candidates_city_fit_score"),
        table_name="product_candidates",
    )
    op.drop_index(
        op.f("ix_product_candidates_eligibility_status"),
        table_name="product_candidates",
    )

    for column in (
        "scoring_version",
        "scoring_method",
        "scoring_confidence",
        "secondary_city_slug",
        "city_fit_scores",
        "city_fit_score",
        "platform_alignment_reasons",
        "platform_alignment_score",
        "eligibility_reasons",
        "eligibility_status",
        "merchant_profile_key",
        "merchant_verification",
    ):
        op.drop_column("product_candidates", column)
