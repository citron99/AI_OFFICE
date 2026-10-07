"""Link immutable reviews to explicit, bounded graph-rework runs."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0011"
down_revision = "20260906_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("rework_parent_task_id", sa.String(40), nullable=True))
        batch.add_column(
            sa.Column(
                "rework_target_node_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
            )
        )
        batch.add_column(
            sa.Column("rework_cycle", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch.create_foreign_key(
            "fk_tasks_rework_parent_task", "tasks", ["rework_parent_task_id"], ["id"]
        )
    op.create_index("ix_tasks_rework_parent_task_id", "tasks", ["rework_parent_task_id"])
    with op.batch_alter_table("result_reviews") as batch:
        batch.add_column(
            sa.Column("target_node_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'"))
        )
        batch.add_column(sa.Column("rework_task_id", sa.String(40), nullable=True))
        batch.create_foreign_key(
            "fk_result_reviews_rework_task", "tasks", ["rework_task_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("result_reviews") as batch:
        batch.drop_constraint("fk_result_reviews_rework_task", type_="foreignkey")
        batch.drop_column("rework_task_id")
        batch.drop_column("target_node_ids")
    op.drop_index("ix_tasks_rework_parent_task_id", table_name="tasks")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("fk_tasks_rework_parent_task", type_="foreignkey")
        batch.drop_column("rework_cycle")
        batch.drop_column("rework_target_node_ids")
        batch.drop_column("rework_parent_task_id")
