"""Composite indexes for the legal radar and accounting sync feeds.

`/api/v1/legal/radar-runs` and `/api/v1/accounting/sync-runs` both filter on
`(company_id, owner_id)` and sort on `created_at DESC`, but only single-column
indexes existed on those tables. Each list call therefore filesorted the whole
tenant. These composites match the exact predicate + ordering pair the two
endpoints emit, following the pattern of migration 20261101_0026.
"""

from alembic import op

revision = "20261102_0027"
down_revision = "20261101_0026"
branch_labels = None
depends_on = None


INDEXES = (
    (
        "legal_change_radar_runs",
        "ix_legal_radar_company_owner_created",
        ("company_id", "owner_id", "created_at"),
    ),
    (
        "accounting_sync_runs",
        "ix_sync_company_owner_created",
        ("company_id", "owner_id", "created_at"),
    ),
)


def upgrade() -> None:
    for table, name, columns in INDEXES:
        op.create_index(name, table, list(columns), unique=False)


def downgrade() -> None:
    for table, name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
