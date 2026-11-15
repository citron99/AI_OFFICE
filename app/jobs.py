"""Celery transports only task IDs. PostgreSQL owns requests and execution state."""

import asyncio
import threading
from collections.abc import Coroutine
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from celery import Celery
from celery.signals import worker_process_shutdown, worker_shutdown
from sqlalchemy import select, text

from app.agents.lawyer import LawyerAgent
from app.config import get_settings
from app.db.tables.tasks import TaskRecord, TaskStepRecord
from app.main import create_app
from app.models.task import TaskCreate
from app.services.approvals import audit
from app.services.knowledge import KnowledgeService
from app.services.tasks import TaskService

settings = get_settings()
celery_app: Any = Celery("ai_office", broker=settings.redis_url)


@dataclass
class _WorkerRuntime:
    """Per-process app, engine, and heavy providers shared by every task."""

    loop: asyncio.AbstractEventLoop
    app: Any
    lifespan: Any


_worker_runtime: _WorkerRuntime | None = None
_worker_runtime_lock = threading.Lock()


def _get_worker_runtime() -> _WorkerRuntime:
    """Build the worker runtime once per process (never per task)."""
    global _worker_runtime
    runtime = _worker_runtime
    if runtime is not None:
        return runtime
    with _worker_runtime_lock:
        if _worker_runtime is None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            app = create_app(settings=settings)
            lifespan = app.router.lifespan_context(app)
            try:
                loop.run_until_complete(lifespan.__aenter__())
            except BaseException:
                loop.close()
                raise
            _worker_runtime = _WorkerRuntime(loop=loop, app=app, lifespan=lifespan)
    assert _worker_runtime is not None
    return _worker_runtime


def _drive[T](loop: asyncio.AbstractEventLoop, coroutine: Coroutine[Any, Any, T]) -> T:
    """Run one coroutine on the persistent loop; cancel it if the task is interrupted."""
    task = loop.create_task(coroutine)
    try:
        return loop.run_until_complete(task)
    except BaseException:
        task.cancel()
        with suppress(BaseException):
            loop.run_until_complete(task)
        raise


def _close_worker_runtime(**_: Any) -> None:
    global _worker_runtime
    runtime, _worker_runtime = _worker_runtime, None
    if runtime is None:
        return
    with suppress(Exception):
        runtime.loop.run_until_complete(runtime.lifespan.__aexit__(None, None, None))
    runtime.loop.close()


worker_process_shutdown.connect(_close_worker_runtime)
worker_shutdown.connect(_close_worker_runtime)


def _make_task_service(session: Any, app: Any) -> TaskService:
    """Factory: TaskService composition root with lawyer and knowledge wiring."""
    return TaskService(
        session,
        app.state.orchestrator,
        app.state.accounting_provider,
        LawyerAgent(
            KnowledgeService(session, settings, app.state.embedding_provider),
            app.state.llm_provider if settings.legal_analysis_enabled else None,
            consultant=app.state.consultant_provider,
        ),
        consultant=app.state.consultant_provider,
    )


celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": 180,
        "socket_timeout": 5,
        "socket_connect_timeout": 3,
    },
    task_soft_time_limit=100,
    task_time_limit=120,
    # The scheduling beat: policy decisions live in scheduler_runner; the
    # schedule itself stays disabled until the owner signs it off.
    beat_schedule={
        "run-due-schedules": {
            "task": "ai_office.run_due_schedules",
            "schedule": 300.0,
        },
    },
)


def run_due_schedules_task() -> int:
    """Tick every enabled schedule; returns the number of runs started."""
    from app.services.scheduler_runner import run_due_schedules as _run

    runtime = _get_worker_runtime()
    return _drive(runtime.loop, _run_due_schedules_async(runtime.app, _run))


celery_app.task(name="ai_office.run_due_schedules")(run_due_schedules_task)


async def _run_due_schedules_async(app: Any, runner: Any) -> int:
    from app.services.sessions import cleanup_expired_sessions

    session_factory = app.state.session_factory
    async with session_factory() as session:
        # Session hygiene rides the same 5-minute beat (TZ REL / 10.1).
        await cleanup_expired_sessions(session)
        results = await runner(
            session,
            provider=app.state.accounting_provider,
            service_factory=lambda s: _make_task_service(s, app),
        )
        started = sum(1 for r in results if r.get("task_id"))
        for result in results:
            print(
                "[beat] schedule tick",
                result.get("company_id"),
                result.get("decision"),
                result.get("task_id") or "-",
            )
        return started


async def execute_stored_task(task_id: str) -> None:
    """Standalone execution outside the Celery worker (scripts, diagnostics)."""
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        await _execute_stored_task(task_id, app)


async def _execute_stored_task(task_id: str, app: Any) -> None:
    if app.state.engine.dialect.name != "postgresql":
        raise RuntimeError("Background execution requires PostgreSQL")
    # Session advisory lock survives service commits and is released on worker loss.
    async with app.state.engine.connect() as lock:
        acquired = await lock.scalar(
            text("SELECT pg_try_advisory_lock(hashtext(:id))"), {"id": task_id}
        )
        if not acquired:
            return
        try:
            async with app.state.session_factory() as session:
                record = await session.scalar(select(TaskRecord).where(TaskRecord.id == task_id))
                if record is None or record.state in {
                    "completed",
                    "failed",
                    "cancelled",
                    "waiting_input",
                    "waiting_approval",
                }:
                    return
                if record.state != "queued":
                    # A prior worker died mid-step. Never silently duplicate its work.
                    record.state = "failed"
                    record.completed_at = record.updated_at = datetime.now(UTC)
                    steps = await session.scalars(
                        select(TaskStepRecord).where(
                            TaskStepRecord.task_id == task_id,
                            TaskStepRecord.state.in_(["running", "queued"]),
                        )
                    )
                    for step in steps:
                        step.state = "queued"
                        step.error_code = "WORKER_INTERRUPTED"
                    # Safe stop: no unregistered effects, resumable from the
                    # last confirmed checkpoint via the retry endpoint.
                    record.state = "failed_safe"
                    audit(
                        session,
                        record,
                        "worker_interrupted",
                        {"retry": "resume_from_checkpoint"},
                    )
                    await session.commit()
                    return
                service = _make_task_service(session, app)
                await service._execute(
                    TaskCreate.model_validate(record.request_data),
                    user_id=record.user_id,
                    company_id=record.company_id,
                    existing_task=record,
                )
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(hashtext(:id))"), {"id": task_id})


def process_task(task_id: str) -> None:
    runtime = _get_worker_runtime()
    _drive(runtime.loop, _execute_stored_task(task_id, runtime.app))


celery_app.task(name="office.process_task")(process_task)


def publish(task_id: str) -> None:
    celery_app.send_task("office.process_task", args=[task_id], task_id=task_id, retry=False)
