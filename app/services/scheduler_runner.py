"""Schedule tick runner: shared by the API endpoint and the Celery beat job."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounting.provider import AccountingProvider
from app.db.tables.schedules import ProcessScheduleRecord
from app.models.task import TaskCreate
from app.services.scheduler import ScheduleConfig, ScheduleDecision, evaluate
from app.services.tasks import TaskService

# The repeatable process the MVP schedules (TZ 14).
SUPPORTED_PROCESS = "daily_cash_and_receivable_risk"

_DAILY_MESSAGE = "Ежедневный контроль денег и рисков неплатежей"


def load_config(record: ProcessScheduleRecord | None) -> ScheduleConfig:
    if record is None:
        return ScheduleConfig(process_id=SUPPORTED_PROCESS)
    return ScheduleConfig.model_validate(record.config)


async def tick_process(
    session: AsyncSession,
    *,
    provider: AccountingProvider,
    service: TaskService,
    company_id: str,
    process_id: str,
    acting_user_id: str,
) -> dict[str, Any]:
    """One scheduling beat for one company/process pair.

    Returns the decision plus the created task id (if any); policy outcomes
    are reported, never raised - only a failed run itself surfaces an error.
    """

    record = await session.scalar(
        select(ProcessScheduleRecord).where(
            ProcessScheduleRecord.company_id == company_id,
            ProcessScheduleRecord.process_id == process_id,
        )
    )
    config = load_config(record)
    watermark = provider.get_sync_watermark() if process_id == SUPPORTED_PROCESS else None
    decision, next_at = evaluate(
        config,
        now_utc=datetime.now(UTC),
        watermark_at=watermark.generated_at if watermark else None,
        last_attempt_at=record.last_attempt_at if record else None,
        last_attempt_ok=bool(record.last_attempt_ok) if record else False,
    )
    if decision != ScheduleDecision.DUE:
        return {"decision": decision.value, "next_run_at": next_at, "task_id": None}

    if record is not None:
        record.last_attempt_at = datetime.now(UTC)
        record.last_attempt_ok = False
        await session.commit()
    response = await service.create_and_execute(
        TaskCreate.model_validate({"message": _DAILY_MESSAGE, "process_id": process_id}),
        user_id=acting_user_id,
        company_id=company_id,
    )
    if record is not None:
        record.last_attempt_ok = response.state == "completed"
        await session.commit()
    return {"decision": decision.value, "next_run_at": next_at, "task_id": response.task_id}


async def run_due_schedules(
    session: AsyncSession,
    *,
    provider: AccountingProvider,
    service_factory: Callable[[AsyncSession], TaskService],
) -> list[dict[str, Any]]:
    """Tick every enabled schedule across companies (the beat entry point)."""

    records = list((await session.scalars(select(ProcessScheduleRecord))).all())
    results: list[dict[str, Any]] = []
    for record in records:
        config = ScheduleConfig.model_validate(record.config)
        if not config.enabled or config.process_id != SUPPORTED_PROCESS or not record.updated_by:
            continue
        outcome = await tick_process(
            session,
            provider=provider,
            service=service_factory(session),
            company_id=record.company_id,
            process_id=config.process_id,
            acting_user_id=record.updated_by,
        )
        results.append({"company_id": record.company_id, **outcome})
    return results
