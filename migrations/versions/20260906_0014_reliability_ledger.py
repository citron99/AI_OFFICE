"""Reliability ledger: checkpoints, provider calls and the dead letter queue."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0014"
down_revision = "20260906_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_checkpoints",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("step_id", sa.String(40), nullable=False),
        sa.Column("node_id", sa.String(80), nullable=True),
        sa.Column("checkpoint_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_checkpoints_task_id", "execution_checkpoints", ["task_id"])
    op.create_index("ix_execution_checkpoints_step_id", "execution_checkpoints", ["step_id"])

    op.create_table(
        "provider_calls",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("step_id", sa.String(40), nullable=True),
        sa.Column("node_id", sa.String(80), nullable=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("route", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("result_hash", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_provider_calls_task_id", "provider_calls", ["task_id"])

    op.create_table(
        "dead_letter_entries",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("step_id", sa.String(40), nullable=True),
        sa.Column("node_id", sa.String(80), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=False),
        sa.Column("error_class", sa.String(120), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(40), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_dead_letter_entries_task_id", "dead_letter_entries", ["task_id"])
    op.create_index("ix_dead_letter_entries_owner_id", "dead_letter_entries", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_dead_letter_entries_owner_id", table_name="dead_letter_entries")
    op.drop_index("ix_dead_letter_entries_task_id", table_name="dead_letter_entries")
    op.drop_table("dead_letter_entries")
    op.drop_index("ix_provider_calls_task_id", table_name="provider_calls")
    op.drop_table("provider_calls")
    op.drop_index("ix_execution_checkpoints_step_id", table_name="execution_checkpoints")
    op.drop_index("ix_execution_checkpoints_task_id", table_name="execution_checkpoints")
    op.drop_table("execution_checkpoints")
