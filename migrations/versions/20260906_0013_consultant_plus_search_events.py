"""Consultant+ mandatory search events journal (LEG-008, TZ appendix D)."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0013"
down_revision = "20260906_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consultant_plus_search_events",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("task_id", sa.String(40), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("owner_id", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("query_id", sa.String(64), nullable=True),
        sa.Column("source_id", sa.String(100), nullable=True),
        sa.Column("jurisdiction", sa.String(8), nullable=True),
        sa.Column("edition", sa.String(80), nullable=True),
        sa.Column("locator", sa.String(120), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_consultant_plus_search_events_task_id", "consultant_plus_search_events", ["task_id"]
    )
    op.create_index(
        "ix_consultant_plus_search_events_owner_id", "consultant_plus_search_events", ["owner_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_consultant_plus_search_events_owner_id", table_name="consultant_plus_search_events"
    )
    op.drop_index(
        "ix_consultant_plus_search_events_task_id", table_name="consultant_plus_search_events"
    )
    op.drop_table("consultant_plus_search_events")
