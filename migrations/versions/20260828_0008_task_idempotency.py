"""Owner-scoped task submission keys."""

import sqlalchemy as sa
from alembic import op

revision = "20260828_0008"
down_revision = "20260828_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(128), nullable=True))
        batch.add_column(sa.Column("request_hash", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_task_owner_key", ["user_id", "idempotency_key"])


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("uq_task_owner_key", type_="unique")
        batch.drop_column("request_hash")
        batch.drop_column("idempotency_key")
