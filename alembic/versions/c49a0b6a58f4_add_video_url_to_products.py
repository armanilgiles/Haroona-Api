"""add video_url to products

Revision ID: c49a0b6a58f4
Revises: 9c1f2a4d5e6f
Create Date: 2026-04-23 20:07:51.959120

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c49a0b6a58f4'
down_revision: Union[str, Sequence[str], None] = '9c1f2a4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('products', sa.Column('video_url', sa.String(length=800), nullable=True))

def downgrade():
    op.drop_column('products', 'video_url')
