"""add merchant_url to products

Revision ID: 346dc0157840
Revises: c49a0b6a58f4
Create Date: 2026-04-28 19:27:44.190605

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '346dc0157840'
down_revision: Union[str, Sequence[str], None] = 'c49a0b6a58f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("merchant_url", sa.Text(), nullable=True))

    op.alter_column(
        "products",
        "affiliate_url",
        existing_type=sa.String(),
        nullable=True,
    )

    op.execute(
        """
        UPDATE products p
        SET merchant_url = n.merchant_url
        FROM awin_product_normalized n
        WHERE p.normalized_row_id = n.id
        AND p.merchant_url IS NULL
        AND n.merchant_url IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE products
        SET merchant_url = affiliate_url
        WHERE merchant_url IS NULL
        AND affiliate_url IS NOT NULL
        AND COALESCE(is_affiliate, false) = false
        """
    )



def downgrade() -> None:
    op.execute(
        """
        UPDATE products
        SET affiliate_url = merchant_url
        WHERE affiliate_url IS NULL
        AND merchant_url IS NOT NULL
        """
    )

    op.alter_column(
        "products",
        "affiliate_url",
        existing_type=sa.String(),
        nullable=False,
    )

    op.drop_column("products", "merchant_url")