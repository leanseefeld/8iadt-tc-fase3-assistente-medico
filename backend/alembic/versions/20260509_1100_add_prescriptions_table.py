"""add prescriptions table

Revision ID: 20260509_1100
Revises: 9fc83ede69ff
Create Date: 2026-05-09 11:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260509_1100"
down_revision = "9fc83ede69ff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prescriptions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("patient_id", sa.String(), nullable=False),
        sa.Column("patient_cpf", sa.String(), nullable=True),
        sa.Column("prescriber_kind", sa.String(), nullable=False),
        sa.Column("prescriber_name", sa.String(), nullable=False),
        sa.Column("prescriber_crm", sa.String(), nullable=True),
        sa.Column("prescriber_crm_uf", sa.String(), nullable=True),
        sa.Column("institution_name", sa.String(), nullable=True),
        sa.Column("institution_cnpj_cnes", sa.String(), nullable=True),
        sa.Column("institution_address", sa.String(), nullable=True),
        sa.Column("institution_phone", sa.String(), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("chat_thread_id", sa.String(), nullable=True),
        sa.Column("decision_flow_run_id", sa.String(), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("archived_reason", sa.String(), nullable=True),
        sa.Column("archived_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prescriptions_patient_id", "prescriptions", ["patient_id"])
    op.create_index("ix_prescriptions_issued_at", "prescriptions", ["issued_at"])
    op.create_index("ix_prescriptions_archived_at", "prescriptions", ["archived_at"])
    op.create_index("ix_prescriptions_chat_thread_id", "prescriptions", ["chat_thread_id"])


def downgrade() -> None:
    op.drop_index("ix_prescriptions_chat_thread_id", table_name="prescriptions")
    op.drop_index("ix_prescriptions_archived_at", table_name="prescriptions")
    op.drop_index("ix_prescriptions_issued_at", table_name="prescriptions")
    op.drop_index("ix_prescriptions_patient_id", table_name="prescriptions")
    op.drop_table("prescriptions")
