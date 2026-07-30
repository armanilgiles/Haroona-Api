"""expand Takeads affiliate-link workflow

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_candidates",
        sa.Column("affiliate_provider", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column("affiliate_provider_reference", sa.Text(), nullable=True),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "affiliate_link_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "affiliate_link_invalidated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "product_candidates",
        sa.Column(
            "affiliate_link_invalidated_by",
            sa.String(length=255),
            nullable=True,
        ),
    )

    op.execute(
        """
        UPDATE product_candidates
        SET affiliate_link_status = CASE
            WHEN affiliate_link_status = 'verified'
                 AND (
                     affiliate_url IS NULL
                     OR affiliate_link_verified_at IS NULL
                 )
                THEN CASE
                    WHEN affiliate_url IS NULL THEN 'not_generated'
                    ELSE 'ready_to_verify'
                END
            WHEN affiliate_link_status = 'not_requested'
                 AND affiliate_url IS NOT NULL
                THEN 'ready_to_verify'
            WHEN affiliate_link_status = 'not_requested' THEN 'not_generated'
            WHEN affiliate_link_status = 'generated'
                 AND affiliate_url IS NOT NULL
                THEN 'ready_to_verify'
            WHEN affiliate_link_status = 'generated' THEN 'not_generated'
            WHEN affiliate_link_status = 'failed'
                 AND affiliate_link_error_code = 'manual_verification_failed'
                THEN 'invalid'
            ELSE affiliate_link_status
        END
        """
    )
    op.execute(
        """
        UPDATE product_candidates
        SET affiliate_provider = 'takeads'
        WHERE affiliate_sub_id IS NOT NULL
           OR affiliate_link_status IN (
               'ready_to_verify',
               'verified',
               'no_eligible_offer',
               'failed',
               'invalid'
           )
        """
    )
    op.execute(
        """
        UPDATE product_candidates
        SET affiliate_link_attempt_count = 1
        WHERE affiliate_link_last_attempted_at IS NOT NULL
          AND affiliate_link_attempt_count = 0
        """
    )

    with op.batch_alter_table("product_candidates") as batch_op:
        batch_op.alter_column(
            "affiliate_link_status",
            existing_type=sa.String(length=30),
            nullable=False,
            server_default="not_generated",
        )
        batch_op.create_check_constraint(
            "ck_product_candidates_affiliate_link_status",
            "affiliate_link_status IN ("
            "'not_generated', 'generating', 'ready_to_verify', 'verified', "
            "'no_eligible_offer', 'failed', 'invalid'"
            ")",
        )


def downgrade() -> None:
    with op.batch_alter_table("product_candidates") as batch_op:
        batch_op.drop_constraint(
            "ck_product_candidates_affiliate_link_status",
            type_="check",
        )
    op.execute(
        """
        UPDATE product_candidates
        SET affiliate_link_status = CASE
            WHEN affiliate_link_status = 'not_generated' THEN 'not_requested'
            WHEN affiliate_link_status = 'ready_to_verify' THEN 'generated'
            WHEN affiliate_link_status IN (
                'generating',
                'no_eligible_offer',
                'invalid'
            ) THEN 'failed'
            ELSE affiliate_link_status
        END
        """
    )
    with op.batch_alter_table("product_candidates") as batch_op:
        batch_op.alter_column(
            "affiliate_link_status",
            existing_type=sa.String(length=30),
            nullable=False,
            server_default="not_requested",
        )
    op.drop_column("product_candidates", "affiliate_link_invalidated_by")
    op.drop_column("product_candidates", "affiliate_link_invalidated_at")
    op.drop_column("product_candidates", "affiliate_link_attempt_count")
    op.drop_column("product_candidates", "affiliate_provider_reference")
    op.drop_column("product_candidates", "affiliate_provider")
