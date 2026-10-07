"""Per-company schedules for repeatable processes."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0019"
down_revision = "20260906_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "process_schedules",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("company_id", sa.String(40), nullable=False),
        sa.Column("process_id", sa.String(80), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_ok", sa.Boolean(), nullable=True),
        sa.Column("updated_by", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "process_id", name="uq_schedule_company_proc"),
    )
    op.create_index("ix_process_schedules_company_id", "process_schedules", ["company_id"])
    op.create_index("ix_process_schedules_process_id", "process_schedules", ["process_id"])


def downgrade() -> None:
    op.drop_index("ix_process_schedules_process_id", table_name="process_schedules")
    op.drop_index("ix_process_schedules_company_id", table_name="process_schedules")
    op.drop_table("process_schedules")
