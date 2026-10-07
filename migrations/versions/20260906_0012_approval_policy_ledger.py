"""Approval ledger per TZ V2.1: policy version, requester identity, decisions."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0012"
down_revision = "20260906_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("approvals") as batch:
        batch.add_column(
            sa.Column(
                "policy_version", sa.String(80), nullable=False, server_default="tz-v2.1-policy-v1"
            )
        )
        batch.add_column(
            sa.Column("requested_by", sa.String(120), nullable=False, server_default="orchestrator")
        )
        batch.add_column(sa.Column("decision_reason", sa.String(300), nullable=True))
        batch.add_column(sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("payment_drafts") as batch:
        batch.alter_column("approval_id", existing_type=sa.String(40), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("payment_drafts") as batch:
        batch.alter_column("approval_id", existing_type=sa.String(40), nullable=False)
    with op.batch_alter_table("approvals") as batch:
        batch.drop_column("invalidated_at")
        batch.drop_column("decision_reason")
        batch.drop_column("requested_by")
        batch.drop_column("policy_version")
