import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agents.dummy import DummyAgent
from app.core.exceptions import InvalidStateTransitionError
from app.db.session import create_session_factory
from app.db.tables import AgentRunRecord, TaskRecord, TaskStepRecord
from app.main import build_orchestrator
from app.models.agent import AgentContext, AgentResult
from app.models.task import TaskCreate
from app.services.tasks import TaskService


class FailingAgent(DummyAgent):
    async def execute(self, context: AgentContext) -> AgentResult:
        raise RuntimeError("Synthetic failure")


async def test_agent_failure_persists_failed_task_and_step(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    orchestrator = build_orchestrator()
    orchestrator.dummy_agent = FailingAgent()
    async with factory() as session:
        with pytest.raises(RuntimeError, match="Synthetic failure"):
            await TaskService(session, orchestrator).create_and_execute(
                TaskCreate(message="Проверь договор"),
                user_id="usr_test",
                company_id="comp_demo",
            )
    async with factory() as session:
        task = (await session.scalars(select(TaskRecord))).one()
        step = (await session.scalars(select(TaskStepRecord))).one()
        assert task.state == "failed"
        assert task.completed_at is not None
        assert step.state == "failed"
        assert step.error_code == "AGENT_EXECUTION_FAILED"


async def test_success_persists_agent_run_and_step_times(engine: AsyncEngine) -> None:
    factory = create_session_factory(engine)
    async with factory() as session:
        result = await TaskService(session, build_orchestrator()).create_and_execute(
            TaskCreate(message="Проверь договор"),
            user_id="usr_test",
            company_id="comp_demo",
        )
    async with factory() as session:
        run = (await session.scalars(select(AgentRunRecord))).one()
        step = (await session.scalars(select(TaskStepRecord))).one()
        assert run.task_id == result.task_id
        assert run.step_id == step.id
        assert run.output == result.result.model_dump(mode="json")
        assert step.started_at is not None
        assert step.completed_at >= step.started_at


async def test_cancellation_cannot_be_overwritten_by_agent_completion(engine: AsyncEngine) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowAgent(DummyAgent):
        async def execute(self, context: AgentContext) -> AgentResult:
            started.set()
            await release.wait()
            return await super().execute(context)

    factory = create_session_factory(engine)
    orchestrator = build_orchestrator()
    orchestrator.dummy_agent = SlowAgent()
    async with factory() as session:
        execution = asyncio.create_task(
            TaskService(session, orchestrator).create_and_execute(
                TaskCreate(message="Проверь договор"),
                user_id="usr_test",
                company_id="comp_demo",
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            async with factory() as other:
                task = (await other.scalars(select(TaskRecord))).one()
                await TaskService(other, build_orchestrator()).cancel(
                    task.id,
                    user_id="usr_test",
                    company_id="comp_demo",
                )
        finally:
            release.set()
        with pytest.raises(InvalidStateTransitionError):
            await asyncio.wait_for(execution, timeout=5)
    async with factory() as session:
        task = (await session.scalars(select(TaskRecord))).one()
        step = (await session.scalars(select(TaskStepRecord))).one()
        assert task.state == "cancelled"
        assert task.result is None
        assert step.state == "cancelled"
