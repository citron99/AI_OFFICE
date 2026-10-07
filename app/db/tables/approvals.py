from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class ApprovalRecord(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("apr"))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # APR-001/003 ledger fields: which policy decided, which machine principal
    # requested the action, and the immutable human decision context.
    policy_version: Mapped[str] = mapped_column(String(80), default="tz-v2.1-policy-v1")
    requested_by: Mapped[str] = mapped_column(String(120), default="orchestrator")
    decision_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DraftRecord(Base):
    __tablename__ = "payment_drafts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("draft"))
    # Null for drafts created inside the ALLOW_DRAFT limit without an approval.
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"), unique=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AuditRecord(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("audit"))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    event: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
