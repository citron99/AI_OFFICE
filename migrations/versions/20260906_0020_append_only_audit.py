"""Enforce append-only audit at the database level, not only in the app."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0020"
down_revision = "20260906_0019"
branch_labels = None
depends_on = None

TABLES = ("audit_events", "consultant_plus_search_events")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for table in TABLES:
            for event in ("UPDATE", "DELETE"):
                bind.execute(
                    sa.text(
                        f"CREATE TRIGGER {table}_no_{event.lower()} BEFORE {event} ON {table} "
                        "BEGIN SELECT RAISE(ABORT, 'append-only: use an explicit new event'); END"
                    )
                )
    else:
        bind.execute(
            sa.text(
                "CREATE OR REPLACE FUNCTION enforce_append_only() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'append-only: use an explicit new event'; END; "
                "$$ LANGUAGE plpgsql"
            )
        )
        for table in TABLES:
            bind.execute(
                sa.text(
                    f"CREATE TRIGGER {table}_append_only "
                    f"BEFORE UPDATE OR DELETE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION enforce_append_only()"
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for table in TABLES:
            for event in ("update", "delete"):
                bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {table}_no_{event}"))
    else:
        for table in TABLES:
            bind.execute(sa.text(f"DROP RULE IF EXISTS {table}_no_update ON {table}"))
            bind.execute(sa.text(f"DROP RULE IF EXISTS {table}_no_delete ON {table}"))
