"""Add dedupe_key to alerts."""

from alembic import op
import sqlalchemy as sa


revision = "20260525_1800"
down_revision = "20260525_1700"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("alerts") as batch:
        batch.add_column(sa.Column("dedupe_key", sa.String(), nullable=True))
    op.create_index(
        op.f("ix_alerts_dedupe_key"),
        "alerts",
        ["dedupe_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_alerts_dedupe_key"), table_name="alerts")
    with op.batch_alter_table("alerts") as batch:
        batch.drop_column("dedupe_key")
