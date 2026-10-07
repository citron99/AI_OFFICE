"""Schedule endpoints: owner-configured run time, calendar and manual tick."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import BusinessOwnerDependency, PrincipalDependency, WriterDependency
from app.api.dependencies import SessionDependency, TaskServiceDependency
from app.db.tables.schedules import ProcessScheduleRecord
from app.services.scheduler import ScheduleConfig, describe
from app.services.scheduler_runner import tick_process

router = APIRouter(tags=["process schedules"])

DEFAULT_CONFIG = ScheduleConfig(process_id="daily_cash_and_receivable_risk")


async def _load(
    session: AsyncSession, company_id: str, process_id: str
) -> ProcessScheduleRecord | None:
    record: ProcessScheduleRecord | None = await session.scalar(
        select(ProcessScheduleRecord).where(
            ProcessScheduleRecord.company_id == company_id,
            ProcessScheduleRecord.process_id == process_id,
        )
    )
    return record


def _config_of(record: ProcessScheduleRecord | None) -> ScheduleConfig:
    if record is None:
        return DEFAULT_CONFIG.model_copy()
    return ScheduleConfig.model_validate(record.config)


@router.get("/processes/{process_id}/schedule")
async def get_schedule(
    process_id: str,
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
) -> dict[str, Any]:
    record = await _load(session, principal.company_id, process_id)
    config = _config_of(record)
    payload = describe(config, now_utc=datetime.now(UTC))
    payload["last_attempt_at"] = record.last_attempt_at if record else None
    payload["last_attempt_ok"] = record.last_attempt_ok if record else None
    # The scheduler only ever targets the repeatable daily process.
    payload["supported"] = process_id == "daily_cash_and_receivable_risk"
    return payload


@router.put("/processes/{process_id}/schedule")
async def put_schedule(
    process_id: str,
    config: ScheduleConfig,
    principal: BusinessOwnerDependency,
    session: SessionDependency,
) -> dict[str, Any]:
    if process_id != config.process_id:
        raise HTTPException(422, "process_id mismatch between path and body")
    record = await _load(session, principal.company_id, process_id)
    if record is None:
        record = ProcessScheduleRecord(
            company_id=principal.company_id,
            process_id=process_id,
            config=config.model_dump(mode="json"),
            updated_by=principal.user_id,
        )
        session.add(record)
    else:
        record.config = config.model_dump(mode="json")
        record.updated_by = principal.user_id
        record.updated_at = datetime.now(UTC)
    await session.commit()
    return describe(ScheduleConfig.model_validate(record.config), now_utc=datetime.now(UTC))


@router.post("/processes/{process_id}/schedule/tick")
async def tick_schedule(
    process_id: str,
    principal: WriterDependency,
    session: SessionDependency,
    request: Request,
    service: TaskServiceDependency,
) -> dict[str, Any]:
    """One scheduling beat: run the process if the policy says it is due.

    In production a Celery beat job calls this; nothing runs when the owner
    has not enabled the schedule or the configured stop-lines hold.
    """

    return await tick_process(
        session,
        provider=request.app.state.accounting_provider,
        service=service,
        company_id=principal.company_id,
        process_id=process_id,
        acting_user_id=principal.user_id,
    )
