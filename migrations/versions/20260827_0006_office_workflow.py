"""Persist full requests, synthetic draft approvals and append-only application audit."""

import sqlalchemy as sa
from alembic import op

revision = "20260827_0006"
down_revision = "20260827_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("request_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(40), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "payment_drafts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "approval_id", sa.String(40), sa.ForeignKey("approvals.id"), nullable=False, unique=True
        ),
        sa.Column("owner_id", sa.String(40), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner_id", sa.String(40), nullable=False, index=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False, index=True),
        sa.Column("event", sa.String(80), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("payment_drafts")
    op.drop_table("approvals")
    op.drop_column("tasks", "request_data")
