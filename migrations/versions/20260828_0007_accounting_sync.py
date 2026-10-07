"""Owner-scoped on-demand mock snapshot receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20260828_0007"
down_revision = "20260827_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounting_sync_runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner_id", sa.String(40), nullable=False, index=True),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("dataset_version", sa.String(100), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_key", name="uq_sync_owner_key"),
    )


def downgrade() -> None:
    op.drop_table("accounting_sync_runs")
