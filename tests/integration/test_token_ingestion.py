from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord
from app.knowledge.embeddings import HashEmbeddingProvider
from app.knowledge.splitting import split_to_fit
from app.main import create_app


class BoundedProvider(HashEmbeddingProvider):
    model_id = "test-bounded-v2"

    def split_text(self, text: str, *, max_parts: int) -> list[str]:
        return split_to_fit(text, lambda value: len(value) <= 60, max_parts=max_parts)

    def embed(self, text: str) -> list[float]:
        assert len(text) <= 60
        return super().embed(text)


async def test_ingestion_and_attachment_queries_fit_without_losing_text(
    engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    factory = create_session_factory(engine)
    settings = Settings(app_env="test", upload_dir=tmp_path, llm_provider="mock")
    app = create_app(
        settings=settings,
        engine=engine,
        session_factory=factory,
        embedding_provider=BoundedProvider(),
    )
    text = "Contract payment notice. " * 30
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
        ) as client:
            upload = await client.post(
                "/api/v1/files",
                files={
                    "file": ("test.txt", text.encode(), "text/plain"),
                },
            )
            artifact = upload.json()["id"]
            source = await client.post(
                "/api/v1/knowledge/sources",
                json={
                    "artifact_id": artifact,
                    "title": "Synthetic",
                    "document_type": "contract",
                    "jurisdiction": "LV",
                    "authority": "Test",
                    "version": "1",
                    "effective_from": "2026-01-01",
                    "status": "ACTIVE",
                },
            )
            assert source.status_code == 201, source.text
            async with factory() as session:
                chunks = (
                    await session.scalars(
                        select(KnowledgeChunkRecord).order_by(
                            KnowledgeChunkRecord.ordinal,
                        )
                    )
                ).all()
                assert len(chunks) > 1
                assert "".join(c.text for c in chunks) == text.strip()
            response = await client.post(
                "/api/v1/tasks",
                json={
                    "message": "Review contract payment",
                    "requested_agent": "lawyer",
                    "jurisdiction": "LV",
                    "effective_on": "2026-08-27",
                    "attachment_ids": [artifact],
                },
            )
            assert response.status_code == 201, response.text
            result = response.json()["result"]
            assert result["status"] == "retrieval_only"
            assert result["documents"][0]["text"] == text.strip()
            # A too-large query workload is rejected before any incomplete review.
            oversized = await client.post(
                "/api/v1/tasks",
                json={
                    "message": "contract " * 1000,
                    "requested_agent": "lawyer",
                    "jurisdiction": "LV",
                    "effective_on": "2026-08-27",
                },
            )
            assert oversized.status_code == 422
            async with factory() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(KnowledgeSourceRecord))
                    == 1
                )
