from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class LegalChangeRadarRunRecord(Base):
    __tablename__ = "legal_change_radar_runs"
    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_legal_radar_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("lcr"))
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    baseline_source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.id"), index=True)
    current_source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.id"), index=True)
    subject: Mapped[str] = mapped_column(Text)
    jurisdiction: Mapped[str] = mapped_column(String(2), index=True)
    effective_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), index=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class LegalChangeRadarReviewRecord(Base):
    __tablename__ = "legal_change_radar_reviews"
    __table_args__ = (UniqueConstraint("run_id", name="uq_legal_radar_review_run"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("lrv"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("legal_change_radar_runs.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str] = mapped_column(String(40), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(40), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
