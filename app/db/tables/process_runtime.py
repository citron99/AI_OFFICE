"""Per-process runtime controls: autonomy ladder and kill switches (TZ 7.1, REL-006)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class ProcessRuntimeRecord(Base):
    __tablename__ = "process_runtime"
    __table_args__ = (UniqueConstraint("company_id", "process_id", name="uq_runtime_company_proc"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rt"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    process_id: Mapped[str] = mapped_column(String(80), index=True)
    # TZ 7.1 autonomy ladder: a0_shadow | a1_recommendation | a2_draft | a3_approved_action.
    autonomy_level: Mapped[str] = mapped_column(String(30), default="a1_recommendation")
    # REL-006: independent kill switches, no code change required.
    process_enabled: Mapped[bool] = mapped_column(default=True)
    llm_enabled: Mapped[bool] = mapped_column(default=True)
    write_tools_enabled: Mapped[bool] = mapped_column(default=True)
    updated_by: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
