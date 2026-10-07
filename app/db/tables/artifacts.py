from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("art"))
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    classification: Mapped[str] = mapped_column(String(32), default="INTERNAL")
    # ART-003: provenance and retention are mandatory artifact metadata.
    source_provenance: Mapped[str] = mapped_column(String(80), default="user_upload")
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dlp_rules: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
