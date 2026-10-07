"""Persist graph-node identity and the immutable budget/usage of each run."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0010"
down_revision = "20260904_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("run_budget_snapshot", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("run_usage", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    with op.batch_alter_table("task_steps") as batch:
        batch.add_column(sa.Column("node_id", sa.String(80), nullable=True))
        batch.add_column(
            sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )


def downgrade() -> None:
    with op.batch_alter_table("task_steps") as batch:
        batch.drop_column("attempt")
        batch.drop_column("node_id")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("run_usage")
        batch.drop_column("run_budget_snapshot")
