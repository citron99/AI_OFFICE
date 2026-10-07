import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_dimension_migration_preserves_rows_and_guards_downgrade() -> None:
    path = Path(__file__).parents[2] / "migrations/versions/20260827_0004_embedding_dimensions.py"
    spec = importlib.util.spec_from_file_location("embedding_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE knowledge_sources (id TEXT PRIMARY KEY)"))
            connection.execute(text("INSERT INTO knowledge_sources (id) VALUES ('preserved')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                row = connection.execute(
                    text("SELECT id, embedding_dimensions FROM knowledge_sources")
                ).one()
                assert row == ("preserved", 128)
                connection.execute(text("UPDATE knowledge_sources SET embedding_dimensions=384"))
                with pytest.raises(RuntimeError, match="Non-128"):
                    migration.downgrade()
                connection.execute(text("UPDATE knowledge_sources SET embedding_dimensions=128"))
                migration.downgrade()
                columns = [c["name"] for c in inspect(connection).get_columns("knowledge_sources")]
                assert columns == ["id"]
                assert connection.scalar(text("SELECT id FROM knowledge_sources")) == "preserved"
    finally:
        engine.dispose()
