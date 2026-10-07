from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class ResultReviewRecord(Base):
    __tablename__ = "result_reviews"
    __table_args__ = (UniqueConstraint("task_id", name="uq_result_review_task"),)

    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("review"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    reviewer_id: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    result_hash: Mapped[str] = mapped_column(String(64))
    target_node_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    rework_task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
