"""add conversation_messages.superseded_by_message_id

Revision ID: 20260525_1700
Revises: 20260525_1600
Create Date: 2026-05-25 17:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260525_1700"
down_revision = "20260525_1600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite: sem FK em ALTER; integridade referencial fica na camada de aplicação.
    op.add_column(
        "conversation_messages",
        sa.Column("superseded_by_message_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_conversation_messages_superseded_by_message_id",
        "conversation_messages",
        ["superseded_by_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_messages_superseded_by_message_id",
        table_name="conversation_messages",
    )
    op.drop_column("conversation_messages", "superseded_by_message_id")
