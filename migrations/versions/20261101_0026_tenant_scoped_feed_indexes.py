"""Composite indexes for owner-scoped activity, approvals and drafts feeds.

Before this migration, `/api/v1/activity`, `/api/v1/tasks` and the approvals /
draft lists filtered on `(company_id, owner_id)` and sorted on a timestamp, but
only single-column indexes existed. That forced a filesort over every tenant's
rows on SQLite/PostgreSQL alike. The composite indexes cover the exact
predicate + ordering pairs those endpoints emit, without adding redundant
indexes for the standalone `company_id`/`owner_id` accesses that already exist.
"""

from alembic import op

revision = "20261101_0026"
down_revision = "20261013_0025"
branch_labels = None
depends_on = None


INDEXES = (
    ("tasks", "ix_tasks_company_owner_created", ("company_id", "user_id", "created_at")),
    ("task_steps", "ix_task_steps_task_started", ("task_id", "started_at", "id")),
    ("audit_events", "ix_audit_company_owner_created", ("company_id", "owner_id", "created_at")),
    ("audit_events", "ix_audit_task_created", ("task_id", "created_at")),
    ("approvals", "ix_approvals_company_owner_expires", ("company_id", "owner_id", "expires_at")),
    ("payment_drafts", "ix_drafts_company_owner_created", ("company_id", "owner_id", "created_at")),
)


def upgrade() -> None:
    for table, name, columns in INDEXES:
        op.create_index(name, table, list(columns), unique=False)


def downgrade() -> None:
    for table, name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
