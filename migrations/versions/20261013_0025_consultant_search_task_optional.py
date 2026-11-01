"""Allow taskless Consultant+ journal rows (manual search and change radar).

A manual `/legal/search` or a change-radar run crosses the perimeter without a
task, so the audit row must be storable with `task_id IS NULL`.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0025"
down_revision = "20261009_0024"
branch_labels = None
depends_on = None

TABLE = "consultant_plus_search_events"


def _reattach_append_only_triggers() -> None:
    """Batch recreate on SQLite drops the 0020 triggers; put them back."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    for event in ("UPDATE", "DELETE"):
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {TABLE}_no_{event.lower()}"))
        bind.execute(
            sa.text(
                f"CREATE TRIGGER {TABLE}_no_{event.lower()} BEFORE {event} ON {TABLE} "
                "BEGIN SELECT RAISE(ABORT, 'append-only: use an explicit new event'); END"
            )
        )


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("task_id", existing_type=sa.String(40), nullable=True)
    _reattach_append_only_triggers()


def downgrade() -> None:
    bind = op.get_bind()
    unattributed = bind.execute(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE task_id IS NULL")
    ).scalar_one()
    if unattributed:
        raise RuntimeError(
            f"{unattributed} journal rows have no task; downgrade would delete audit evidence"
        )
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("task_id", existing_type=sa.String(40), nullable=False)
    _reattach_append_only_triggers()
