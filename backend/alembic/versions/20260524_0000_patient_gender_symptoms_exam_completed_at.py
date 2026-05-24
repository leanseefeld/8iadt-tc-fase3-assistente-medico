"""add patient gender/symptoms and exam completed_at

Revision ID: 20260524_0000
Revises: 20260509_1100
Create Date: 2026-05-24 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260524_0000"
down_revision = "20260509_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("gender", sa.String(), nullable=True))
    op.add_column(
        "patients",
        sa.Column("symptoms", sa.String(), nullable=False, server_default=""),
    )
    op.add_column("exams", sa.Column("completed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("exams", "completed_at")
    op.drop_column("patients", "symptoms")
    op.drop_column("patients", "gender")
