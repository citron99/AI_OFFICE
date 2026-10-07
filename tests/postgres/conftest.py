"""Opt-in PostgreSQL tests: no fallback to the application DATABASE_URL."""

import os
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture
def postgres_test_url() -> str:
    value = os.environ.get("TEST_POSTGRES_URL")
    if not value:
        pytest.skip("TEST_POSTGRES_URL is required for real PostgreSQL tests")
    url = make_url(value)
    if url.drivername != "postgresql+asyncpg" or not url.database:
        raise ValueError("TEST_POSTGRES_URL must specify a postgresql+asyncpg test database")
    return value


def migrate(connection: Connection, revision: str = "head", *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["connection"] = connection
    schema = connection.scalar(text("SELECT current_schema()"))
    if not isinstance(schema, str) or not re.fullmatch(r"ai_office_test_[0-9a-f]{32}", schema):
        raise ValueError("Migrations must target the generated test schema, never public")
    # Do not accidentally read a public.alembic_version from an existing application.
    config.attributes["version_table_schema"] = schema
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


@pytest.fixture
def migration_runner() -> Callable[..., None]:
    return migrate


@pytest_asyncio.fixture
async def pg_engine(postgres_test_url: str) -> AsyncIterator[AsyncEngine]:
    schema = "ai_office_test_" + uuid4().hex
    assert re.fullmatch(r"ai_office_test_[0-9a-f]{32}", schema)
    admin = create_async_engine(postgres_test_url, connect_args={"timeout": 5})
    engine = create_async_engine(
        postgres_test_url,
        connect_args={
            "timeout": 5,
            "server_settings": {
                "search_path": f"{schema},public",
                "statement_timeout": "10000",
                "lock_timeout": "5000",
            },
        },
    )
    created = False
    try:
        async with admin.begin() as connection:
            # This is an explicitly configured test DB; keep a shared extension on cleanup.
            await connection.execute(
                text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            )
            await connection.execute(CreateSchema(schema))
        created = True
        async with engine.begin() as connection:
            await connection.run_sync(migrate)
        yield engine
    finally:
        await engine.dispose()
        if created:
            async with admin.begin() as connection:
                # Drop only the UUID schema created above, never public or the database.
                await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()
