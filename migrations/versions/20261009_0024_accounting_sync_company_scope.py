"""Tighten accounting sync idempotency to company scope."""

import sqlalchemy as sa
from alembic import op

revision = "20261009_0024"
down_revision = "20261005_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE accounting_sync_runs SET company_id = 'comp_demo' WHERE company_id IS NULL")
    )
    with op.batch_alter_table("accounting_sync_runs") as batch:
        batch.drop_constraint("uq_sync_owner_key", type_="unique")
    with op.batch_alter_table("accounting_sync_runs") as batch:
        batch.create_unique_constraint(
            "uq_sync_company_owner_key", ["company_id", "owner_id", "request_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("accounting_sync_runs") as batch:
        batch.drop_constraint("uq_sync_company_owner_key", type_="unique")
    with op.batch_alter_table("accounting_sync_runs") as batch:
        batch.create_unique_constraint("uq_sync_owner_key", ["owner_id", "request_key"])
