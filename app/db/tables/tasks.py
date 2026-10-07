from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import new_id
from app.db.base import Base


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_task_company_key"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("task"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), index=True)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_text: Mapped[str] = mapped_column(Text)
    attachment_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    requested_agent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    request_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    process_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    rework_parent_task_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("tasks.id"), nullable=True, index=True
    )
    rework_target_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    rework_cycle: Mapped[int] = mapped_column(default=0)
    run_budget_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    run_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["TaskStepRecord"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskStepRecord(Base):
    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("step"))
    task_id: Mapped[str] = mapped_column(String(40), ForeignKey("tasks.id"), index=True)
    agent_type: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(200))
    node_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state: Mapped[str] = mapped_column(String(32))
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    input_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempt: Mapped[int] = mapped_column(default=0)

    task: Mapped[TaskRecord] = relationship(back_populates="steps")
