from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db.base import Base


def test_all_migrations_use_supplied_connection_and_match_models() -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            config.attributes["version_table_schema"] = "main"
            for target in ("head", "base", "head"):
                if target == "base":
                    command.downgrade(config, target)
                    assert inspect(connection).get_table_names() == ["alembic_version"]
                else:
                    command.upgrade(config, target)
                    expected = set(Base.metadata.tables) | {"alembic_version"}
                    assert set(inspect(connection).get_table_names()) == expected
                    context = MigrationContext.configure(connection, opts={"compare_type": True})
                    assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()
