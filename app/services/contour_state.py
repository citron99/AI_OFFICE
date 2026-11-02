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

# TZ 7.1: only A2+ sits on the autonomy ladder high enough to produce drafts.
DRAFT_AUTONOMY_LEVELS: frozenset[str] = frozenset({"a2_draft", "a3_approved_action"})


def runtime_allows_draft(runtime: "ProcessRuntimeState") -> bool:
    """Single source of truth for "may this runtime still create a payment draft?".

    Used by the policy gate at run time and re-checked at approval decision time,
    so an OWNER who flips a kill switch or lowers the autonomy ceiling while an
    approval sits pending cannot have the draft slip through (TZ 7.1, REL-006).
    """
    return (
        runtime.process_enabled
        and runtime.write_tools_enabled
        and runtime.autonomy_level in DRAFT_AUTONOMY_LEVELS
    )


class ProcessRuntimeState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    process_id: str
    # TZ 7.1: the pilot starts at A1 and the ladder rises only on measured
    # quality. Model defaults must fail closed: if a caller forgets to pass
    # a level, or a fresh tenant has no ProcessRuntimeRecord, the safe answer
    # is "no drafts" — never "A2 allowed by default".
    autonomy_level: AutonomyLevel = "a1_recommendation"
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
    """Current switches; every process starts safely at A1 with writes disabled."""
    record = await session.scalar(
        select(ProcessRuntimeRecord).where(
            ProcessRuntimeRecord.company_id == company_id,
            ProcessRuntimeRecord.process_id == process_id,
        )
    )
    if record is None:
        # TZ 7.1 + AGENTS.md ("autonomy ceilings ... fail-closed"): a tenant
        # with no ProcessRuntimeRecord is untrusted and cannot produce drafts.
        # The ladder only rises on measured quality, via update_runtime.
        return ProcessRuntimeState(process_id=process_id)
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
