"""Reliability ledger: checkpoints, provider calls and the dead letter queue.

TZ V2.1 section 11: state is persisted before and after external calls
(REL-001), every provider call is journalled without secrets (12.1), and
exhausted nodes land in the DLQ with a reason and an owner for the review
(REL-005).
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class ExecutionCheckpointRecord(Base):
    """A confirmed node completion a restart can resume from (REL-001)."""

    __tablename__ = "execution_checkpoints"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("chk"))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    step_id: Mapped[str] = mapped_column(String(40), index=True)
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # SHA-256 over the confirmed output mapping at the moment of the checkpoint.
    checkpoint_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(30), default="node_completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProviderCallRecord(Base):
    """Metadata journal of one external agent/provider call (no payloads)."""

    __tablename__ = "provider_calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prv"))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    step_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider: Mapped[str] = mapped_column(String(80))
    operation: Mapped[str] = mapped_column(String(120))
    # Machine principal (agt_accountant, ...) that performed the call.
    machine_identity: Mapped[str | None] = mapped_column(String(40), nullable=True)
    route: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # succeeded | failed
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DeadLetterEntryRecord(Base):
    """A run that exhausted its retries, kept for bounded human review."""

    __tablename__ = "dead_letter_entries"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("dlq"))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    step_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_code: Mapped[str] = mapped_column(String(80))
    error_class: Mapped[str] = mapped_column(String(120), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    resolved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
