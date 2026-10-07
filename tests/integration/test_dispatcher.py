from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.dispatcher import dispatch_pending
from app.models.task import TaskCreate
from app.repositories.tasks import TaskRepository


async def test_recovers_only_stale_queued_tasks(engine: AsyncEngine, monkeypatch):
    from app import jobs

    sent = []
    monkeypatch.setattr(jobs, "publish", sent.append)
    async with create_session_factory(engine)() as session:
        repo = TaskRepository(session)
        stale = await repo.create(
            user_id="owner",
            payload=TaskCreate(message="old queued"),
            company_id="comp_demo",
        )
        stale.updated_at = datetime.now(UTC) - timedelta(minutes=1)
        await repo.create(
            user_id="owner",
            payload=TaskCreate(message="new queued"),
            company_id="comp_demo",
        )
        done = await repo.create(
            user_id="owner",
            payload=TaskCreate(message="already done"),
            company_id="comp_demo",
        )
        done.state = "completed"
        done.updated_at = stale.updated_at
        await session.commit()
        assert await dispatch_pending(session) == 1
        assert sent == [stale.id]


async def test_broker_failure_preserves_recoverable_record(engine: AsyncEngine, monkeypatch):
    from app import jobs

    def fail(_):
        raise OSError("secret broker password")

    monkeypatch.setattr(jobs, "publish", fail)
    async with create_session_factory(engine)() as session:
        record = await TaskRepository(session).create(
            user_id="owner",
            payload=TaskCreate(message="recover"),
            company_id="comp_demo",
        )
        record.updated_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
        assert await dispatch_pending(session) == 0
        await session.refresh(record)
        assert record.state == "queued"
