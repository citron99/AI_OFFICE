from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def create_engine(
    database_url: str, *, echo: bool = False, connect_args: dict[str, object] | None = None
) -> AsyncEngine:
    kwargs: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
    if connect_args:
        kwargs["connect_args"] = connect_args
    if database_url == "sqlite+aiosqlite:///:memory:":
        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_async_engine(database_url, **kwargs)
    if database_url.startswith("sqlite+"):

        @event.listens_for(engine.sync_engine, "connect")
        def enable_sqlite_pragmas(connection, record) -> None:  # type: ignore[no-untyped-def]
            del record
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # File-based SQLite serves concurrent writers only with WAL and a
            # busy timeout; the in-memory pilot DB is single-connection.
            if database_url != "sqlite+aiosqlite:///:memory:":
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
