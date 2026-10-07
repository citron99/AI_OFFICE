import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_reindex_migration_preserves_chunks_and_enforces_uniqueness() -> None:
    path = Path(__file__).parents[2] / "migrations/versions/20260827_0005_reindex_identity.py"
    spec = importlib.util.spec_from_file_location("reindex_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.execute(
                text(
                    "CREATE TABLE knowledge_sources (id TEXT PRIMARY KEY, "
                    "embedding_model TEXT, embedding_dimensions INTEGER)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE knowledge_chunks (id TEXT PRIMARY KEY, "
                    "source_id TEXT REFERENCES knowledge_sources(id) ON DELETE CASCADE)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_sources VALUES ('original','mock',128),"
                    "('copy1','semantic',3),('copy2','semantic',3)"
                )
            )
            connection.execute(text("INSERT INTO knowledge_chunks VALUES ('preserved','original')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                assert connection.scalar(text("SELECT count(*) FROM knowledge_chunks")) == 1
                connection.execute(
                    text("UPDATE knowledge_sources SET reindex_of_id='original' WHERE id='copy1'")
                )
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE knowledge_sources SET reindex_of_id='original' WHERE id='copy2'"
                        )
                    )
                assert connection.scalar(text("SELECT count(*) FROM knowledge_sources")) == 3
                migration.downgrade()
                assert connection.scalar(text("SELECT count(*) FROM knowledge_chunks")) == 1
                assert "reindex_of_id" not in {
                    c["name"] for c in inspect(connection).get_columns("knowledge_sources")
                }
    finally:
        engine.dispose()
