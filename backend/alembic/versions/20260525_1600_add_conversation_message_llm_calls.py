"""add conversation_message_llm_calls table

Revision ID: 20260525_1600
Revises: 20260524_1400
Create Date: 2026-05-25 16:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260525_1600"
down_revision = "20260524_1400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_message_llm_calls",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("assistant_message_id", sa.String(), nullable=False),
        sa.Column("call_type", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("llm_input", sa.JSON(), nullable=False),
        sa.Column("llm_output", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"],
            ["conversation_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_message_llm_calls_assistant_message_id",
        "conversation_message_llm_calls",
        ["assistant_message_id"],
    )
    op.create_index(
        "ix_conversation_message_llm_calls_call_type",
        "conversation_message_llm_calls",
        ["call_type"],
    )
    op.create_index(
        "ix_conversation_message_llm_calls_created_at",
        "conversation_message_llm_calls",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("conversation_message_llm_calls")
