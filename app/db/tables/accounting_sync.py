from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class AccountingSyncRecord(Base):
    __tablename__ = "accounting_sync_runs"
    __table_args__ = (UniqueConstraint("owner_id", "request_key", name="uq_sync_owner_key"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sync"))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    request_key: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(100))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    counts: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
