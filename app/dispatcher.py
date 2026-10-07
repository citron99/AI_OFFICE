"""Recover durable queued tasks when a process dies before broker publication.

Task rows are the outbox. Delivery is at least once; workers own the execution lock.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.db.tables.tasks import TaskRecord
from app.services.approvals import expire_pending_approvals

logger = logging.getLogger(__name__)


async def dispatch_pending(session: AsyncSession) -> int:
    from app.jobs import publish

    # Grace avoids ordinary enqueue races. Repeated delivery is intentional and safe.
    cutoff = datetime.now(UTC) - timedelta(seconds=30)
    task_ids = list(
        await session.scalars(
            select(TaskRecord.id)
            .where(TaskRecord.state == "queued", TaskRecord.updated_at < cutoff)
            .order_by(TaskRecord.updated_at, TaskRecord.id)
            .limit(100)
        )
    )
    delivered = 0
    for task_id in task_ids:
        try:
            await asyncio.to_thread(publish, task_id)
        except Exception:
            # No credentials or broker exception bodies in logs; retry next cycle.
            logger.warning("queue_publication_unavailable")
            break
        delivered += 1
    return delivered


async def run() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    if engine.dialect.name != "postgresql":
        await engine.dispose()
        raise RuntimeError("Dispatcher requires PostgreSQL")
    factory = create_session_factory(engine)
    try:
        while True:
            try:
                async with factory() as session:
                    await expire_pending_approvals(session)
            except Exception:
                logger.warning("approval_expiry_unavailable")
            try:
                async with factory() as session:
                    await dispatch_pending(session)
            except Exception:
                logger.warning("queue_recovery_unavailable")
            await asyncio.sleep(10)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
