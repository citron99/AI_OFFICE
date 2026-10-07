"""Celery beat schedule runner: enabled schedules tick, disabled ones never run."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.db.tables.schedules import ProcessScheduleRecord
from app.services.scheduler_runner import SUPPORTED_PROCESS, tick_process


async def _save_schedule(
    session_factory,
    *,
    company_id: str,
    process_id: str,
    enabled: bool,
    updated_by: str = "owner-sched",
) -> None:
    async with session_factory() as session:
        session.add(
            ProcessScheduleRecord(
                company_id=company_id,
                process_id=process_id,
                config={
                    "process_id": process_id,
                    "enabled": enabled,
                    "timezone": "Europe/Riga",
                    "run_at": "00:00",  # always past at evaluation time
                    "workdays_only": False,
                },
                updated_by=updated_by,
            )
        )
        await session.commit()


async def test_disabled_schedule_never_runs(engine: AsyncEngine) -> None:
    from app.accounting.mock import Mock1CConnector

    factory = create_session_factory(engine)
    await _save_schedule(
        factory, company_id="comp_demo", process_id=SUPPORTED_PROCESS, enabled=False
    )
    async with factory() as session:
        outcome = await tick_process(
            session,
            provider=Mock1CConnector(),
            service=None,  # type: ignore[arg-type]
            company_id="comp_demo",
            process_id=SUPPORTED_PROCESS,
            acting_user_id="owner-sched",
        )
    assert outcome["decision"] == "disabled"
    assert outcome["task_id"] is None


async def test_enabled_schedule_creates_the_daily_task(engine: AsyncEngine) -> None:
    from app.accounting.mock import Mock1CConnector
    from app.db.tables.tasks import TaskRecord
    from app.main import build_orchestrator
    from app.services.tasks import TaskService

    factory = create_session_factory(engine)
    await _save_schedule(
        factory, company_id="comp_demo", process_id=SUPPORTED_PROCESS, enabled=True
    )
    async with factory() as session:
        service = TaskService(session, build_orchestrator(), Mock1CConnector())
        outcome = await tick_process(
            session,
            provider=Mock1CConnector(),
            service=service,
            company_id="comp_demo",
            process_id=SUPPORTED_PROCESS,
            acting_user_id="owner-sched",
        )
    assert outcome["decision"] == "due"
    assert outcome["task_id"]
    async with factory() as session:
        task = await session.get(TaskRecord, outcome["task_id"])
        assert task is not None
        assert task.company_id == "comp_demo"
        schedule = (await session.scalars(select(ProcessScheduleRecord))).first()
        assert schedule.last_attempt_at is not None


async def test_run_due_schedules_covers_companies_and_skips_disabled(
    engine: AsyncEngine,
) -> None:
    from app.accounting.mock import Mock1CConnector
    from app.main import build_orchestrator
    from app.services.scheduler_runner import run_due_schedules
    from app.services.tasks import TaskService

    factory = create_session_factory(engine)
    await _save_schedule(factory, company_id="comp_a", process_id=SUPPORTED_PROCESS, enabled=True)
    await _save_schedule(factory, company_id="comp_b", process_id=SUPPORTED_PROCESS, enabled=False)
    async with factory() as session:
        results = await run_due_schedules(
            session,
            provider=Mock1CConnector(),
            service_factory=lambda s: TaskService(s, build_orchestrator(), Mock1CConnector()),
        )
    # Only the enabled company's schedule produced a run.
    assert [r["company_id"] for r in results if r.get("task_id")] == ["comp_a"]
