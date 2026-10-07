import asyncio
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.db.tables.tasks import TaskRecord
from app.main import build_orchestrator
from app.models.task import TaskCreate
from app.repositories.tasks import TaskRepository
from app.services.tasks import TaskService


async def test_concurrent_submission_publishes_once(pg_engine: AsyncEngine) -> None:
    factory = create_session_factory(pg_engine)

    async def submit():
        async with factory() as session:
            return await TaskService(session, build_orchestrator()).enqueue(
                TaskCreate(message="Hello"),
                user_id="new-owner",
                idempotency_key="one",
                company_id="comp_demo",
            )

    with patch("app.jobs.publish") as publish:
        results = await asyncio.gather(*(submit() for _ in range(5)))
    assert len({result.task_id for result in results}) == 1
    publish.assert_called_once()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(TaskRecord)) == 1


async def test_owner_scope_and_immutable_fingerprint(pg_engine: AsyncEngine) -> None:
    factory = create_session_factory(pg_engine)
    payload = TaskCreate(message="Original")
    async with factory() as session:
        repo = TaskRepository(session)
        first, created = await repo.create_once(
            user_id="one", payload=payload, key="same", company_id="comp_demo"
        )
        assert created
        first.request_data = {"message": "Clarified"}
        first.state = "failed"
        await session.commit()
        replay, created = await repo.create_once(
            user_id="one", payload=payload, key="same", company_id="comp_demo"
        )
        assert not created
        assert replay.id == first.id
        assert replay.state == "failed"
        # TZ TASK-002: the key scope is the company, so another user of the same
        # company replays the same task; a different company creates its own.
        colleague, created = await repo.create_once(
            user_id="two", payload=payload, key="same", company_id="comp_demo"
        )
        assert not created
        assert colleague.id == first.id
        other, created = await repo.create_once(
            user_id="two", payload=payload, key="same", company_id="comp_other"
        )
        assert created
        assert other.id != first.id
        await session.commit()


async def test_concurrent_inline_submission_executes_once(pg_engine: AsyncEngine) -> None:
    factory = create_session_factory(pg_engine)
    orchestrator = build_orchestrator()

    async def submit():
        async with factory() as session:
            return await TaskService(session, orchestrator).create_and_execute(
                TaskCreate(message="Hello"),
                user_id="new-owner",
                idempotency_key="inline",
                company_id="comp_demo",
            )

    with patch.object(orchestrator, "execute", wraps=orchestrator.execute) as execute:
        results = await asyncio.gather(*(submit() for _ in range(5)))
    assert len({result.task_id for result in results}) == 1
    execute.assert_called_once()
