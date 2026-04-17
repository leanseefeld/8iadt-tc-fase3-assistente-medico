"""initial schema

Revision ID: 20260417_1200
Revises:
Create Date: 2026-04-17 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260417_1200"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("sex", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cid_code", sa.String(), nullable=False),
        sa.Column("cid_label", sa.String(), nullable=False),
        sa.Column("observations", sa.String(), nullable=False),
        sa.Column("comorbidities", sa.JSON(), nullable=False),
        sa.Column("current_medications", sa.JSON(), nullable=False),
    )

    op.create_table(
        "vital_signs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("blood_pressure", sa.String(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("oxygen_saturation", sa.Integer(), nullable=False),
        sa.Column("heart_rate", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vital_signs_patient_id", "vital_signs", ["patient_id"])
    op.create_index("ix_vital_signs_recorded_at", "vital_signs", ["recorded_at"])

    op.create_table(
        "exams",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result", sa.String(), nullable=True),
        sa.Column("interpretation", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("protocol_ref", sa.String(), nullable=True),
        sa.Column("attachment_name", sa.String(), nullable=True),
        sa.Column("attachment_mime", sa.String(), nullable=True),
        sa.Column("attachment_size", sa.Integer(), nullable=True),
        sa.Column("attachment_path", sa.String(), nullable=True),
    )
    op.create_index("ix_exams_patient_id", "exams", ["patient_id"])

    op.create_table(
        "suggested_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("protocol_ref", sa.String(), nullable=True),
    )
    op.create_index("ix_suggested_items_patient_id", "suggested_items", ["patient_id"])

    op.create_table(
        "agent_log_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.String(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_log_entries_patient_id", "agent_log_entries", ["patient_id"])
    op.create_index("ix_agent_log_entries_timestamp", "agent_log_entries", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_agent_log_entries_timestamp", table_name="agent_log_entries")
    op.drop_index("ix_agent_log_entries_patient_id", table_name="agent_log_entries")
    op.drop_table("agent_log_entries")

    op.drop_index("ix_suggested_items_patient_id", table_name="suggested_items")
    op.drop_table("suggested_items")

    op.drop_index("ix_exams_patient_id", table_name="exams")
    op.drop_table("exams")

    op.drop_index("ix_vital_signs_recorded_at", table_name="vital_signs")
    op.drop_index("ix_vital_signs_patient_id", table_name="vital_signs")
    op.drop_table("vital_signs")

    op.drop_table("patients")
