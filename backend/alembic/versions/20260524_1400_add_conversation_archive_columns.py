"""add archive columns to conversations

Revision ID: 20260524_1400
Revises: 20260524_1200
Create Date: 2026-05-24 14:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260524_1400"
down_revision = "20260524_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column("conversations", sa.Column("archived_by", sa.String(), nullable=True))
    op.create_index("ix_conversations_archived_at", "conversations", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_conversations_archived_at", table_name="conversations")
    op.drop_column("conversations", "archived_by")
    op.drop_column("conversations", "archived_at")
