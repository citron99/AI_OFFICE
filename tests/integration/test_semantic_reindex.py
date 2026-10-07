from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.core.exceptions import ArtifactNotFoundError, FileValidationError
from app.db.session import create_session_factory
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord
from app.knowledge.embeddings import HashEmbeddingProvider
from app.main import create_app
from app.models.knowledge import SearchRequest
from app.services.knowledge import KnowledgeService


class SemanticStub:
    """Deliberately fake vectors test plumbing, not semantic model accuracy."""

    semantic = True
    model_id = "test-semantic-v1"
    dimensions = 3

    def embed(self, text: str) -> list[float]:
        return [1, 0, 0] if "payment" in text or "remuneration" in text else [0, 1, 0]


async def test_reindex_preserves_old_citations_and_isolates_models(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    settings = Settings(app_env="test", upload_dir=tmp_path / "uploads", llm_provider="mock")
    factory = create_session_factory(engine)
    app = create_app(settings=settings, engine=engine, session_factory=factory)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            uploaded = await client.post(
                "/api/v1/files", files={"file": ("test.txt", b"payment", "text/plain")}
            )
            created = await client.post(
                "/api/v1/knowledge/sources",
                json={
                    "artifact_id": uploaded.json()["id"],
                    "title": "SYNTHETIC",
                    "jurisdiction": "LV",
                    "document_type": "contract",
                    "authority": "Fixture only",
                    "version": "1",
                    "effective_from": "2026-01-01",
                    "status": "ACTIVE",
                },
            )
            assert created.status_code == 201
            original = created.json()
            async with factory() as session:
                old_chunk = await session.scalar(
                    select(KnowledgeChunkRecord).where(
                        KnowledgeChunkRecord.source_id == original["id"]
                    )
                )
                assert old_chunk is not None
                old_chunk_id, old_vector = old_chunk.id, list(old_chunk.embedding)
            app.state.embedding_provider = SemanticStub()
            query = {"query": "remuneration", "jurisdiction": "LV", "effective_on": "2026-08-27"}
            before = await client.post("/api/v1/knowledge/search", json=query)
            assert before.json()["hits"] == []
            response = await client.post(f"/api/v1/knowledge/sources/{original['id']}/reindex")
            assert response.status_code == 200, response.text
            new = response.json()
            assert new["id"] != original["id"]
            assert new["embedding_dimensions"] == 3
            assert new["reindex_of_id"] == original["id"]
            assert new["sha256"] == original["sha256"]
            after = await client.post("/api/v1/knowledge/search", json=query)
            assert after.json()["retrieval_version"] == "semantic-cosine-v1"
            assert after.json()["embedding_dimensions"] == 3
            assert after.json()["hits"][0]["source_id"] == new["id"]
            assert not any("MOCK" in w for w in after.json()["warnings"])
            again = await client.post(f"/api/v1/knowledge/sources/{new['id']}/reindex")
            assert again.json()["id"] == new["id"]
            repeated = await client.post(f"/api/v1/knowledge/sources/{original['id']}/reindex")
            assert repeated.status_code == 200
            assert repeated.json()["id"] == new["id"]
            async with factory() as session:
                preserved = await session.get(KnowledgeChunkRecord, old_chunk_id)
                assert preserved is not None and preserved.embedding == old_vector
                assert (
                    await session.scalar(select(func.count()).select_from(KnowledgeSourceRecord))
                    == 2
                )
                mock = KnowledgeService(session, settings, HashEmbeddingProvider())
                result = await mock.search(
                    SearchRequest(
                        query="payment", jurisdiction="LV", effective_on=date(2026, 8, 27)
                    ),
                    owner_id="usr_demo_owner",
                    company_id="comp_demo",
                )
                assert [h.source_id for h in result.hits] == [original["id"]]
                semantic = KnowledgeService(session, settings, SemanticStub())
                with pytest.raises(ArtifactNotFoundError):
                    await semantic.reindex(
                        original["id"],
                        owner_id="foreign",
                        company_id="comp_demo",
                    )

            # Simulate a stale pre-insert read; the real DB uniqueness error must
            # roll back and return the already committed winner, not create a clone.
            class StaleReadService(KnowledgeService):
                calls = 0

                async def _find_reindex(
                    self, source_id: str, owner_id: str, company_id: str
                ) -> KnowledgeSourceRecord | None:
                    self.calls += 1
                    if self.calls == 1:
                        return None
                    return await super()._find_reindex(source_id, owner_id, company_id)

            async with factory() as session:
                stale = StaleReadService(session, settings, SemanticStub())
                winner = await stale.reindex(
                    original["id"],
                    owner_id="usr_demo_owner",
                    company_id="comp_demo",
                )
                assert winner.id == new["id"]
                assert stale.calls == 2
                count = await session.scalar(
                    select(func.count()).select_from(KnowledgeSourceRecord)
                )
                assert count == 2


async def test_failed_embeddings_leave_no_index(engine: AsyncEngine, tmp_path: Path) -> None:
    # Use the full HTTP ingestion path to check transaction safety for malformed vectors.
    class Broken(SemanticStub):
        def embed(self, text: str) -> list[float]:
            return [float("nan"), 0, 0]

    settings = Settings(app_env="test", upload_dir=tmp_path / "uploads", llm_provider="mock")
    factory = create_session_factory(engine)
    app = create_app(
        settings=settings, engine=engine, session_factory=factory, embedding_provider=Broken()
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            uploaded = await client.post(
                "/api/v1/files", files={"file": ("test.txt", b"payment", "text/plain")}
            )
            response = await client.post(
                "/api/v1/knowledge/sources",
                json={
                    "artifact_id": uploaded.json()["id"],
                    "title": "Test",
                    "jurisdiction": "LV",
                    "document_type": "contract",
                    "authority": "Test",
                    "version": "1",
                    "effective_from": "2026-01-01",
                },
            )
            assert response.status_code == 422
            async with factory() as session:
                assert (
                    await session.scalar(select(func.count()).select_from(KnowledgeSourceRecord))
                    == 0
                )
                with pytest.raises(FileValidationError):
                    await KnowledgeService(session, settings, Broken()).search(
                        SearchRequest(
                            query="test", jurisdiction="LV", effective_on=date(2026, 8, 27)
                        ),
                        owner_id="usr_demo_owner",
                        company_id="comp_demo",
                    )
