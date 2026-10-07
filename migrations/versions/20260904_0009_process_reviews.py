"""Pin process contracts and store immutable result acceptance separately."""

import sqlalchemy as sa
from alembic import op

revision = "20260904_0009"
down_revision = "20260828_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("process_snapshot", sa.JSON(), nullable=True))
    op.create_table(
        "result_reviews",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_result_review_task"),
    )


def downgrade() -> None:
    op.drop_table("result_reviews")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("process_snapshot")
