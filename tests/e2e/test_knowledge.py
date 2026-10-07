import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.artifacts import ArtifactRecord
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord
from app.knowledge.embeddings import RETRIEVAL_VERSION, HashEmbeddingProvider
from app.models.knowledge import SearchRequest
from app.services.knowledge import KnowledgeService


async def upload(
    client: httpx.AsyncClient, text: str = "Article 1\nContract payment terms."
) -> str:
    response = await client.post(
        "/api/v1/files",
        files={
            "file": ("synthetic.txt", text.encode(), "text/plain"),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def source_payload(artifact_id: str, **changes: object) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "title": "SYNTHETIC contract",
        "jurisdiction": "LV",
        "document_type": "contract",
        "authority": "Synthetic pilot, not law",
        "version": "1",
        "effective_from": "2026-01-01",
        "status": "ACTIVE",
        **changes,
    }


def query(**changes: object) -> dict[str, object]:
    return {
        "query": "Contract payment",
        "jurisdiction": "LV",
        "effective_on": "2026-08-27",
        **changes,
    }


async def test_upload_ingest_search_with_citable_locations(client: httpx.AsyncClient) -> None:
    artifact_id = await upload(client)
    response = await client.post("/api/v1/knowledge/sources", json=source_payload(artifact_id))
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["chunk_count"] == 1
    assert source["embedding_model"].startswith("mock-")
    assert "owner_id" not in source
    search = await client.post("/api/v1/knowledge/search", json=query())
    assert search.status_code == 200, search.text
    hit = search.json()["hits"][0]
    assert hit["source_id"] == source["id"]
    assert hit["article"] == "Article 1"
    assert hit["page"] is None
    assert hit["locator"] == "text; part 1"
    assert hit["version"] == "1"
    assert hit["score"] > 0
    assert search.json()["warnings"]


@pytest.mark.parametrize(
    "changes",
    [
        {"jurisdiction": "DE"},
        {"status": "DRAFT"},
        {"status": "APPROVED"},
        {"status": "REVOKED"},
        {"status": "SUPERSEDED"},
        {"status": "EXPIRED"},
        {"effective_from": "2027-01-01"},
        {"effective_to": "2026-08-26"},
        {"classification": "CONFIDENTIAL"},
        {"classification": "RESTRICTED"},
    ],
)
async def test_ineligible_sources_never_returned(
    client: httpx.AsyncClient,
    changes: dict[str, object],
) -> None:
    artifact_id = await upload(client)
    source = await client.post(
        "/api/v1/knowledge/sources", json=source_payload(artifact_id, **changes)
    )
    assert source.status_code == 201, source.text
    search = await client.post("/api/v1/knowledge/search", json=query())
    assert search.status_code == 200
    assert search.json()["hits"] == []


async def test_owner_isolation_and_foreign_artifact_rejected(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
) -> None:
    artifact_id = await upload(client)
    created = await client.post("/api/v1/knowledge/sources", json=source_payload(artifact_id))
    assert created.status_code == 201
    async with create_session_factory(engine)() as session:
        service = KnowledgeService(session, Settings(app_env="test"))
        result = await service.search(
            SearchRequest.model_validate(query()),
            owner_id="other-user",
            company_id="comp_demo",
        )
        assert result.hits == []
        await session.execute(
            update(ArtifactRecord)
            .where(ArtifactRecord.id == artifact_id)
            .values(owner_id="other-user")
        )
        await session.commit()
    response = await client.post("/api/v1/knowledge/sources", json=source_payload(artifact_id))
    assert response.status_code == 404


async def test_date_boundaries_type_filter_and_top_k(client: httpx.AsyncClient) -> None:
    artifact_id = await upload(client)
    for version in ("1", "2", "3"):
        response = await client.post(
            "/api/v1/knowledge/sources",
            json=source_payload(
                artifact_id,
                version=version,
                effective_from="2026-08-27",
                effective_to="2026-08-27",
            ),
        )
        assert response.status_code == 201
    response = await client.post("/api/v1/knowledge/search", json=query(top_k=2))
    assert len(response.json()["hits"]) == 2
    response = await client.post("/api/v1/knowledge/search", json=query(document_types=["nda"]))
    assert response.json()["hits"] == []
    response = await client.post("/api/v1/knowledge/search", json=query(effective_on="2026-08-28"))
    assert response.json()["hits"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"jurisdiction": ""},
        {"jurisdiction": "Latvia"},
        {"status": "UNKNOWN"},
        {"effective_to": "2025-01-01"},
        {"title": " "},
        {"owner_id": "other-user"},
    ],
)
async def test_invalid_metadata_rejected(
    client: httpx.AsyncClient, changes: dict[str, object]
) -> None:
    response = await client.post(
        "/api/v1/knowledge/sources", json=source_payload("missing", **changes)
    )
    assert response.status_code == 422


async def test_bad_document_does_not_leave_partial_index(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
) -> None:
    artifact_id = await upload(client, "   ")
    response = await client.post("/api/v1/knowledge/sources", json=source_payload(artifact_id))
    assert response.status_code == 422
    async with create_session_factory(engine)() as session:
        assert await session.scalar(select(func.count()).select_from(KnowledgeSourceRecord)) == 0
        assert await session.scalar(select(func.count()).select_from(KnowledgeChunkRecord)) == 0


async def test_stored_hash_mismatch_rejected(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    artifact_id = await upload(client)
    async with create_session_factory(engine)() as session:
        await session.execute(
            update(ArtifactRecord)
            .where(ArtifactRecord.id == artifact_id)
            .values(
                sha256="0" * 64,
            )
        )
        await session.commit()
    response = await client.post("/api/v1/knowledge/sources", json=source_payload(artifact_id))
    assert response.status_code == 422
    assert "hash mismatch" in response.json()["message"]


@pytest.mark.parametrize(
    "changes",
    [
        {"top_k": 0},
        {"query": " "},
        {"owner_id": "other"},
        {"classifications": ["RESTRICTED"]},
        {"status": "DRAFT"},
    ],
)
async def test_search_does_not_accept_access_policy_overrides(
    client: httpx.AsyncClient,
    changes: dict[str, object],
) -> None:
    response = await client.post("/api/v1/knowledge/search", json=query(**changes))
    assert response.status_code == 422


async def test_hash_collision_is_removed_before_top_k(client: httpx.AsyncClient) -> None:
    provider = HashEmbeddingProvider()
    seen: dict[tuple[float, ...], str] = {}
    left = right = ""
    # Pigeonhole principle: 129 different single words must collide in 128 buckets.
    for number in range(129):
        word = f"collision{number}"
        vector = tuple(provider.embed(word))
        if vector in seen:
            left, right = seen[vector], word
            break
        seen[vector] = word
    assert left and right and left != right
    false_id = await upload(client, left)
    response = await client.post("/api/v1/knowledge/sources", json=source_payload(false_id))
    assert response.status_code == 201
    response = await client.post("/api/v1/knowledge/search", json=query(query=right, top_k=1))
    assert response.json()["hits"] == []
    assert response.json()["retrieval_version"] == RETRIEVAL_VERSION
    true_id = await upload(client, right + " real context")
    created = await client.post("/api/v1/knowledge/sources", json=source_payload(true_id))
    response = await client.post("/api/v1/knowledge/search", json=query(query=right, top_k=1))
    assert response.json()["hits"][0]["source_id"] == created.json()["id"]


async def test_candidate_overflow_is_explicit(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.knowledge.MAX_SEARCH_CANDIDATES", 1)
    artifact_id = await upload(client)
    for version in ["1", "2"]:
        response = await client.post(
            "/api/v1/knowledge/sources", json=source_payload(artifact_id, version=version)
        )
        assert response.status_code == 201
    response = await client.post("/api/v1/knowledge/search", json=query())
    assert response.status_code == 422
    assert "candidate limit" in response.json()["message"]
