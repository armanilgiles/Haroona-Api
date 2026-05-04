"""create analytics events

Revision ID: a7b4c9d2e8f1
Revises: 83b81b1890bc
Create Date: 2026-05-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7b4c9d2e8f1"
down_revision: Union[str, Sequence[str], None] = "83b81b1890bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_name", sa.String(length=80), nullable=False),
        sa.Column("anonymous_id", sa.String(length=120), nullable=True),
        sa.Column("session_id", sa.String(length=120), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("product_id", sa.String(length=200), nullable=True),
        sa.Column("db_product_id", sa.Integer(), nullable=True),
        sa.Column("city_slug", sa.String(length=80), nullable=True),
        sa.Column("city_name", sa.String(length=120), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("referrer", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["db_product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(op.f("ix_analytics_events_id"), "analytics_events", ["id"], unique=False)
    op.create_index(op.f("ix_analytics_events_event_name"), "analytics_events", ["event_name"], unique=False)
    op.create_index(op.f("ix_analytics_events_anonymous_id"), "analytics_events", ["anonymous_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_session_id"), "analytics_events", ["session_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_user_id"), "analytics_events", ["user_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_product_id"), "analytics_events", ["product_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_db_product_id"), "analytics_events", ["db_product_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_city_slug"), "analytics_events", ["city_slug"], unique=False)
    op.create_index(op.f("ix_analytics_events_created_at"), "analytics_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_analytics_events_created_at"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_city_slug"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_db_product_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_product_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_user_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_session_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_anonymous_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_event_name"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_id"), table_name="analytics_events")
    op.drop_table("analytics_events")
