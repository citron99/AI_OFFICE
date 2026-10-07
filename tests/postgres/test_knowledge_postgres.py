import asyncio
import io
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import Connection, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.datastructures import Headers

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord
from app.knowledge.embeddings import EmbeddingProvider, HashEmbeddingProvider
from app.models.knowledge import SearchRequest, SourceCreate, SourceResponse
from app.services.files import FileService
from app.services.knowledge import KnowledgeService


class SemanticVectors:
    """Synthetic vectors test pgvector mechanics, not model relevance."""

    semantic = True
    model_id = "pg-semantic-v1"
    dimensions = 3

    def embed(self, text: str) -> list[float]:
        return [1, 0, 0] if "payment" in text or "remuneration" in text else [0, 1, 0]


@pytest.fixture
def pg_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        llm_provider="mock",
        embedding_provider="mock",
        upload_dir=tmp_path / "uploads",
        semantic_min_score=0.3,
    )


async def seed(
    engine: AsyncEngine,
    settings: Settings,
    provider: EmbeddingProvider,
    *,
    owner_id: str = "owner",
    jurisdiction: str = "LV",
) -> SourceResponse:
    async with create_session_factory(engine)() as session:
        artifact = await FileService(session, settings).upload(
            UploadFile(
                filename="synthetic.txt",
                file=io.BytesIO(b"payment"),
                headers=Headers({"content-type": "text/plain"}),
            ),
            owner_id=owner_id,
            company_id="comp_demo",
        )
        return await KnowledgeService(session, settings, provider).ingest(
            SourceCreate(
                artifact_id=artifact.id,
                title="SYNTHETIC source",
                jurisdiction=jurisdiction,
                document_type="contract",
                authority="TEST ONLY",
                version="1",
                status="ACTIVE",
                effective_from=date(2026, 1, 1),
            ),
            owner_id=owner_id,
            company_id="comp_demo",
        )


async def test_pg_mixed_dimensions_and_access_filters(
    pg_engine: AsyncEngine,
    pg_settings: Settings,
) -> None:
    old = await seed(pg_engine, pg_settings, HashEmbeddingProvider())
    desired = await seed(pg_engine, pg_settings, SemanticVectors())
    await seed(pg_engine, pg_settings, SemanticVectors(), owner_id="foreign")
    await seed(pg_engine, pg_settings, SemanticVectors(), jurisdiction="DE")
    async with create_session_factory(pg_engine)() as session:
        query = SearchRequest(
            query="remuneration",
            jurisdiction="LV",
            effective_on=date(2026, 8, 27),
        )
        result = await KnowledgeService(session, pg_settings, SemanticVectors()).search(
            query,
            owner_id="owner",
            company_id="comp_demo",
        )
        assert [hit.source_id for hit in result.hits] == [desired.id]
        assert result.hits[0].score == pytest.approx(1.0)
        assert result.retrieval_version == "semantic-cosine-v1"
        old_chunk = await session.scalar(
            select(KnowledgeChunkRecord).where(
                KnowledgeChunkRecord.source_id == old.id,
            )
        )
        assert old_chunk is not None and len(old_chunk.embedding) == 128


async def test_pg_concurrent_reindex_publishes_one_copy(
    pg_engine: AsyncEngine,
    pg_settings: Settings,
) -> None:
    original = await seed(pg_engine, pg_settings, HashEmbeddingProvider())
    barrier = asyncio.Barrier(2)

    class ConcurrentService(KnowledgeService):
        first_lookup = True

        async def _find_reindex(
            self, source_id: str, owner_id: str, company_id: str
        ) -> KnowledgeSourceRecord | None:
            found = await super()._find_reindex(source_id, owner_id, company_id)
            if self.first_lookup:
                self.first_lookup = False
                assert found is None
                await barrier.wait()
            return found

    async def run_request() -> SourceResponse:
        async with create_session_factory(pg_engine)() as session:
            service = ConcurrentService(session, pg_settings, SemanticVectors())
            return await service.reindex(
                original.id,
                owner_id="owner",
                company_id="comp_demo",
            )

    async with asyncio.timeout(20):
        first, second = await asyncio.gather(run_request(), run_request())
    assert first.id == second.id != original.id
    async with create_session_factory(pg_engine)() as session:
        copies = await session.scalar(
            select(func.count())
            .select_from(KnowledgeSourceRecord)
            .where(
                KnowledgeSourceRecord.reindex_of_id == original.id,
            )
        )
        assert copies == 1
        assert await session.scalar(select(func.count()).select_from(KnowledgeChunkRecord)) == 2


async def test_pg_migrations_preserve_existing_vectors(
    pg_engine: AsyncEngine,
    pg_settings: Settings,
    migration_runner: Callable[..., None],
) -> None:
    original = await seed(pg_engine, pg_settings, HashEmbeddingProvider())

    def roundtrip(connection: Connection) -> None:
        migration_runner(connection, "20260827_0003", downgrade=True)
        vector_type = connection.scalar(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid='knowledge_chunks'::regclass AND attname='embedding'"
            )
        )
        assert vector_type == "vector(128)"
        migration_runner(connection)
        assert connection.scalar(text("SELECT count(*) FROM knowledge_chunks")) == 1

    async with pg_engine.begin() as connection:
        await connection.run_sync(roundtrip)
    async with create_session_factory(pg_engine)() as session:
        record = await session.get(KnowledgeSourceRecord, original.id)
        assert record is not None and record.embedding_dimensions == 128
        assert record.reindex_of_id is None
