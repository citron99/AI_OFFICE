import importlib.util
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

TABLE = "consultant_plus_search_events"


def _load_migration() -> Callable[[], None]:
    path = (
        Path(__file__).parents[2]
        / "migrations/versions/20261013_0025_consultant_search_task_optional.py"
    )
    spec = importlib.util.spec_from_file_location("licensed_journal_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_schema(connection: Connection) -> None:
    """The database as revision 20261009_0024 left it: NOT NULL task_id + triggers."""
    connection.execute(
        text("CREATE TABLE tasks (id TEXT PRIMARY KEY, company_id TEXT, user_id TEXT)")
    )
    connection.execute(
        text(
            f"CREATE TABLE {TABLE} ("
            "id TEXT PRIMARY KEY, company_id TEXT, task_id TEXT NOT NULL "
            "REFERENCES tasks(id), owner_id TEXT NOT NULL, outcome TEXT NOT NULL, "
            "query_id TEXT, source_id TEXT, jurisdiction TEXT, edition TEXT, locator TEXT, "
            "effective_from DATE, effective_to DATE, searched_at DATETIME NOT NULL, "
            "details JSON NOT NULL)"
        )
    )
    for event in ("UPDATE", "DELETE"):
        connection.execute(
            text(
                f"CREATE TRIGGER {TABLE}_no_{event.lower()} BEFORE {event} ON {TABLE} "
                "BEGIN SELECT RAISE(ABORT, 'append-only: use an explicit new event'); END"
            )
        )
    connection.execute(text("INSERT INTO tasks VALUES ('t1','comp_demo','usr_demo_owner')"))
    connection.execute(
        text(
            f"INSERT INTO {TABLE} "
            "(id, company_id, task_id, owner_id, outcome, searched_at, details) VALUES "
            "('e1','comp_demo','t1','usr_demo_owner','found','2026-10-13 00:00:00','{}')"
        )
    )


def _insert_taskless(connection: Connection) -> None:
    connection.execute(
        text(
            f"INSERT INTO {TABLE} "
            "(id, company_id, task_id, owner_id, outcome, searched_at, details) VALUES "
            "('e2','comp_demo',NULL,'usr_demo_owner','egress_blocked','2026-10-13 00:00:01','{}')"
        )
    )


def _with_schema(run) -> None:  # type: ignore[no-untyped-def]
    migration = _load_migration()
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            _seed_schema(connection)
            with Operations.context(MigrationContext.configure(connection)):
                run(migration, connection)
    finally:
        engine.dispose()


def test_upgrade_allows_taskless_rows_and_keeps_append_only() -> None:
    def run(migration, connection: Connection) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(IntegrityError), connection.begin_nested():
            _insert_taskless(connection)
        migration.upgrade()
        columns = inspect(connection).get_columns(TABLE)
        assert next(c for c in columns if c["name"] == "task_id")["nullable"] is True
        _insert_taskless(connection)
        assert connection.scalar(text(f"SELECT count(*) FROM {TABLE}")) == 2
        for statement in (
            f"UPDATE {TABLE} SET outcome='found' WHERE id='e2'",
            f"DELETE FROM {TABLE} WHERE id='e2'",
        ):
            with pytest.raises(IntegrityError, match="append-only"), connection.begin_nested():
                connection.execute(text(statement))
        # Rows that do name a task stay under FK control.
        with pytest.raises(IntegrityError, match="FOREIGN KEY"), connection.begin_nested():
            connection.execute(
                text(
                    f"INSERT INTO {TABLE} "
                    "(id, company_id, task_id, owner_id, outcome, searched_at, details) VALUES "
                    "('e3','comp_demo','nope','usr_demo_owner','found',"
                    "'2026-10-13 00:00:02','{}')"
                )
            )

    _with_schema(run)


def test_downgrade_refuses_to_discard_taskless_journal_rows() -> None:
    def run(migration, connection: Connection) -> None:  # type: ignore[no-untyped-def]
        migration.upgrade()
        _insert_taskless(connection)
        with pytest.raises(RuntimeError, match="audit evidence"):
            migration.downgrade()
        assert connection.scalar(text(f"SELECT count(*) FROM {TABLE}")) == 2

    _with_schema(run)


def test_downgrade_restores_not_null_when_every_row_has_a_task() -> None:
    def run(migration, connection: Connection) -> None:  # type: ignore[no-untyped-def]
        migration.upgrade()
        migration.downgrade()
        columns = inspect(connection).get_columns(TABLE)
        assert next(c for c in columns if c["name"] == "task_id")["nullable"] is False
        assert connection.scalar(text(f"SELECT count(*) FROM {TABLE}")) == 1

    _with_schema(run)
