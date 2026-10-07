"""Company contour: companies, memberships and company scope everywhere."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0015"
down_revision = "20260906_0014"
branch_labels = None
depends_on = None

_BOOTSTRAP_COMPANY = "comp_demo"


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "company_memberships",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("company_id", sa.String(40), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "user_id", name="uq_membership_company_user"),
    )
    op.create_index("ix_company_memberships_company_id", "company_memberships", ["company_id"])
    op.create_index("ix_company_memberships_user_id", "company_memberships", ["user_id"])

    # Bootstrap company for pre-existing single-company data (portable SQL).
    from datetime import UTC, datetime

    bind = op.get_bind()
    inserted = bind.execute(
        sa.text("SELECT id FROM companies WHERE id = :company_id"),
        {"company_id": _BOOTSTRAP_COMPANY},
    ).first()
    if inserted is None:
        bind.execute(
            sa.text(
                "INSERT INTO companies (id, name, status, created_at) "
                "VALUES (:company_id, :name, 'active', :created_at)"
            ),
            {
                "company_id": _BOOTSTRAP_COMPANY,
                "name": "Demo Investment Company",
                "created_at": datetime.now(UTC),
            },
        )

    def add_company(table: str, nullable: bool = True) -> None:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("company_id", sa.String(40), nullable=True))
        if not nullable:
            bind.execute(
                sa.text(f"UPDATE {table} SET company_id = :company_id WHERE company_id IS NULL"),
                {"company_id": _BOOTSTRAP_COMPANY},
            )
            with op.batch_alter_table(table) as batch:
                batch.alter_column("company_id", existing_type=sa.String(40), nullable=False)
        op.create_index(f"ix_{table}_company_id", table, ["company_id"])

    for table in [
        "tasks",
        "approvals",
        "payment_drafts",
        "audit_events",
        "artifacts",
        "knowledge_sources",
        "accounting_sync_runs",
        "result_reviews",
        "consultant_plus_search_events",
        "execution_checkpoints",
        "provider_calls",
        "dead_letter_entries",
    ]:
        add_company(table, nullable=table != "tasks")

    # TZ TASK-002: idempotency is scoped by company, not by user.
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("uq_task_owner_key", type_="unique")
        batch.create_unique_constraint("uq_task_company_key", ["company_id", "idempotency_key"])


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("uq_task_company_key", type_="unique")
        batch.create_unique_constraint("uq_task_owner_key", ["user_id", "idempotency_key"])

    for table in [
        "dead_letter_entries",
        "provider_calls",
        "execution_checkpoints",
        "consultant_plus_search_events",
        "result_reviews",
        "accounting_sync_runs",
        "knowledge_sources",
        "artifacts",
        "audit_events",
        "payment_drafts",
        "approvals",
        "tasks",
    ]:
        op.drop_index(f"ix_{table}_company_id", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("company_id")

    op.drop_index("ix_company_memberships_user_id", table_name="company_memberships")
    op.drop_index("ix_company_memberships_company_id", table_name="company_memberships")
    op.drop_table("company_memberships")
    op.drop_table("companies")
