"""add exam_attachments table

Revision ID: 20260417_1300
Revises: 20260417_1200
Create Date: 2026-04-17 13:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260417_1300"
down_revision = "20260417_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_attachments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("exam_id", sa.String(), sa.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
    )
    op.create_index("ix_exam_attachments_exam_id", "exam_attachments", ["exam_id"])


def downgrade() -> None:
    op.drop_index("ix_exam_attachments_exam_id", table_name="exam_attachments")
    op.drop_table("exam_attachments")
