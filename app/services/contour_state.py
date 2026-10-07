"""Runtime contour state: autonomy ladder and kill switches per process."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables.process_runtime import ProcessRuntimeRecord

AutonomyLevel = Literal["a0_shadow", "a1_recommendation", "a2_draft", "a3_approved_action"]

AUTONOMY_LEVELS: tuple[str, ...] = (
    "a0_shadow",
    "a1_recommendation",
    "a2_draft",
    "a3_approved_action",
)


class ProcessRuntimeState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    process_id: str
    # TZ 7.1: the pilot process starts at A1; interactive tooling may default
    # to A2. The ladder rises on measured quality, never by default.
    autonomy_level: AutonomyLevel = "a2_draft"
    process_enabled: bool = True
    llm_enabled: bool = True
    write_tools_enabled: bool = True
    updated_by: str | None = None
    updated_at: datetime | None = None


class ProcessRuntimeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autonomy_level: AutonomyLevel | None = None
    process_enabled: bool | None = None
    llm_enabled: bool | None = None
    write_tools_enabled: bool | None = None


async def get_runtime(
    session: AsyncSession, *, company_id: str, process_id: str
) -> ProcessRuntimeState:
    """Current switches; the pilot process starts safely at A1."""
    record = await session.scalar(
        select(ProcessRuntimeRecord).where(
            ProcessRuntimeRecord.company_id == company_id,
            ProcessRuntimeRecord.process_id == process_id,
        )
    )
    if record is None:
        # The repeatable daily process is the 30-day pilot contour (TZ 14):
        # it starts at A1 recommendation; interactive tooling defaults to A2.
        start = (
            "a1_recommendation" if process_id == "daily_cash_and_receivable_risk" else "a2_draft"
        )
        return ProcessRuntimeState(process_id=process_id, autonomy_level=start)
    return ProcessRuntimeState.model_validate(record)


async def update_runtime(
    session: AsyncSession,
    *,
    company_id: str,
    process_id: str,
    update: ProcessRuntimeUpdate,
    updated_by: str,
) -> ProcessRuntimeState:
    record = await session.scalar(
        select(ProcessRuntimeRecord).where(
            ProcessRuntimeRecord.company_id == company_id,
            ProcessRuntimeRecord.process_id == process_id,
        )
    )
    if record is None:
        record = ProcessRuntimeRecord(
            company_id=company_id, process_id=process_id, updated_by=updated_by
        )
        session.add(record)
    if update.autonomy_level is not None:
        record.autonomy_level = update.autonomy_level
    if update.process_enabled is not None:
        record.process_enabled = update.process_enabled
    if update.llm_enabled is not None:
        record.llm_enabled = update.llm_enabled
    if update.write_tools_enabled is not None:
        record.write_tools_enabled = update.write_tools_enabled
    record.updated_by = updated_by
    record.updated_at = datetime.now(UTC)
    await session.commit()
    return ProcessRuntimeState.model_validate(record)
