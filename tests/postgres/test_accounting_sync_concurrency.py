import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.accounting.mock import Mock1CConnector
from app.db.session import create_session_factory
from app.db.tables.accounting_sync import AccountingSyncRecord
from app.services.accounting_sync import sync_snapshot


async def test_concurrent_sync_returns_single_receipt(pg_engine: AsyncEngine) -> None:
    factory = create_session_factory(pg_engine)

    async def sync():
        async with factory() as session:
            return await sync_snapshot(
                session, Mock1CConnector(), owner_id="owner", request_key="concurrent-key"
            )

    first, second = await asyncio.gather(sync(), sync())
    assert first == second
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AccountingSyncRecord)) == 1
