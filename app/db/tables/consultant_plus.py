from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class ConsultantPlusSearchEventRecord(Base):
    """Append-only journal of mandatory Consultant+ searches (LEG-008).

    Metadata only: query and source identifiers, edition and locator. The
    licensed full text is never copied here.
    """

    __tablename__ = "consultant_plus_search_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cps"))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    outcome: Mapped[str] = mapped_column(String(20))  # found | not_found | unavailable
    query_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    edition: Mapped[str | None] = mapped_column(String(80), nullable=True)
    locator: Mapped[str | None] = mapped_column(String(120), nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
