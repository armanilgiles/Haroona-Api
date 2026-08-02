"""add candidate publish destination preference

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_candidates",
        sa.Column(
            "publish_destination",
            sa.String(length=20),
            nullable=False,
            server_default="affiliate",
        ),
    )
    with op.batch_alter_table("product_candidates") as batch_op:
        batch_op.create_check_constraint(
            "ck_product_candidates_publish_destination",
            "publish_destination IN ('affiliate', 'retailer')",
        )


def downgrade() -> None:
    with op.batch_alter_table("product_candidates") as batch_op:
        batch_op.drop_constraint(
            "ck_product_candidates_publish_destination",
            type_="check",
        )
    op.drop_column("product_candidates", "publish_destination")
