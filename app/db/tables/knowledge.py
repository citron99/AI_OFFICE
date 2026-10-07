from datetime import UTC, date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base
from app.knowledge.embeddings import DIMENSIONS


class KnowledgeSourceRecord(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        Index(
            "uq_knowledge_reindex_target",
            "reindex_of_id",
            "embedding_model",
            "embedding_dimensions",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("src"))
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    company_id: Mapped[str | None] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(255))
    jurisdiction: Mapped[str] = mapped_column(String(2), index=True)
    document_type: Mapped[str] = mapped_column(String(255))
    authority: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(255))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32))
    classification: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(2))
    sha256: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding_dimensions: Mapped[int] = mapped_column(
        Integer, default=DIMENSIONS, server_default="128"
    )
    chunk_count: Mapped[int] = mapped_column(Integer)
    # When the RAG cache entry was indexed (LEG-007 freshness policy).
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    reindex_of_id: Mapped[str | None] = mapped_column(String(40), nullable=True)


class KnowledgeChunkRecord(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("chk"))
    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(255))
    page: Mapped[int | None] = mapped_column(Integer)
    article: Mapped[str | None] = mapped_column(String(255))
    embedding: Mapped[list[float]] = mapped_column(Vector().with_variant(JSON(), "sqlite"))
