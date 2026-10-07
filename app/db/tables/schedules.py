"""Per-company schedules for repeatable processes (TZ 14)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class ProcessScheduleRecord(Base):
    __tablename__ = "process_schedules"
    __table_args__ = (
        UniqueConstraint("company_id", "process_id", name="uq_schedule_company_proc"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sch"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    process_id: Mapped[str] = mapped_column(String(80), index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_ok: Mapped[bool | None] = mapped_column(default=None)
    updated_by: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
