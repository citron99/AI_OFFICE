"""Machine principals and capability grants ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0017"
down_revision = "20260906_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_grants",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("company_id", sa.String(40), nullable=False),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("step_id", sa.String(40), nullable=False),
        sa.Column("node_id", sa.String(80), nullable=False),
        sa.Column("principal_id", sa.String(40), nullable=False),
        sa.Column("data_scope", sa.String(30), nullable=False),
        sa.Column("actions", sa.String(400), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_capability_grants_company_id", "capability_grants", ["company_id"])
    op.create_index("ix_capability_grants_task_id", "capability_grants", ["task_id"])
    op.create_index("ix_capability_grants_step_id", "capability_grants", ["step_id"])
    with op.batch_alter_table("provider_calls") as batch:
        batch.add_column(sa.Column("machine_identity", sa.String(40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("provider_calls") as batch:
        batch.drop_column("machine_identity")
    op.drop_index("ix_capability_grants_step_id", table_name="capability_grants")
    op.drop_index("ix_capability_grants_task_id", table_name="capability_grants")
    op.drop_index("ix_capability_grants_company_id", table_name="capability_grants")
    op.drop_table("capability_grants")
