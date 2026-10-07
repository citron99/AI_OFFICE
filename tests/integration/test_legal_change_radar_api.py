from datetime import date

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.db.tables.artifacts import ArtifactRecord
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord


async def _seed_versions(engine: AsyncEngine) -> tuple[str, str]:
    async with create_session_factory(engine)() as session:
        artifacts = [
            ArtifactRecord(
                id="art_radar_old",
                company_id="comp_demo",
                owner_id="usr_demo_owner",
                filename="old.txt",
                mime_type="text/plain",
                size_bytes=40,
                storage_key="radar-old",
                sha256="a" * 64,
                classification="INTERNAL",
            ),
            ArtifactRecord(
                id="art_radar_new",
                company_id="comp_demo",
                owner_id="usr_demo_owner",
                filename="new.txt",
                mime_type="text/plain",
                size_bytes=70,
                storage_key="radar-new",
                sha256="b" * 64,
                classification="INTERNAL",
            ),
        ]
        sources = [
            KnowledgeSourceRecord(
                id="src_radar_old",
                artifact_id=artifacts[0].id,
                company_id="comp_demo",
                owner_id="usr_demo_owner",
                title="Synthetic contract regulation",
                jurisdiction="LV",
                document_type="regulation",
                authority="Synthetic authority",
                version="2025.1",
                effective_from=date(2025, 1, 1),
                effective_to=date(2025, 12, 31),
                status="SUPERSEDED",
                classification="INTERNAL",
                language="en",
                sha256=artifacts[0].sha256,
                embedding_model="mock-token-hash-v1-128",
                embedding_dimensions=128,
                chunk_count=1,
            ),
            KnowledgeSourceRecord(
                id="src_radar_new",
                artifact_id=artifacts[1].id,
                company_id="comp_demo",
                owner_id="usr_demo_owner",
                title="Synthetic contract regulation",
                jurisdiction="LV",
                document_type="regulation",
                authority="Synthetic authority",
                version="2026.1",
                effective_from=date(2026, 1, 1),
                effective_to=None,
                status="ACTIVE",
                classification="INTERNAL",
                language="en",
                sha256=artifacts[1].sha256,
                embedding_model="mock-token-hash-v1-128",
                embedding_dimensions=128,
                chunk_count=1,
            ),
        ]
        chunks = [
            KnowledgeChunkRecord(
                id="chk_radar_old",
                source_id=sources[0].id,
                ordinal=0,
                text="Payment is due monthly.",
                locator="article 7",
                page=1,
                article="7",
                embedding=[0.0] * 128,
            ),
            KnowledgeChunkRecord(
                id="chk_radar_new",
                source_id=sources[1].id,
                ordinal=0,
                text="Payment is due weekly and a penalty applies after the deadline.",
                locator="article 7",
                page=1,
                article="7",
                embedding=[0.0] * 128,
            ),
        ]
        session.add_all(artifacts)
        await session.flush()
        session.add_all(sources)
        await session.flush()
        session.add_all(chunks)
        await session.commit()
    return sources[0].id, sources[1].id


async def test_change_radar_is_idempotent_cited_and_human_reviewed(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    baseline_id, current_id = await _seed_versions(engine)
    payload = {
        "baseline_source_id": baseline_id,
        "current_source_id": current_id,
        "subject": "contract payment acceptance",
        "jurisdiction": "LV",
        "effective_on": "2026-08-27",
    }
    headers = {"Idempotency-Key": "radar-test-001"}

    created = await client.post("/api/v1/legal/change-radar/runs", json=payload, headers=headers)
    replay = await client.post("/api/v1/legal/change-radar/runs", json=payload, headers=headers)

    assert created.status_code == replay.status_code == 201, created.text
    assert created.json()["id"] == replay.json()["id"]
    result = created.json()["result"]
    assert result["status"] == "awaiting_legal_review"
    assert result["changes"][0]["before"]["quote"] == "Payment is due monthly."
    assert result["changes"][0]["after"]["quote"].startswith("Payment is due weekly")
    assert result["consultant_plus"]["queries"]
    assert "text" not in result["consultant_plus"]["queries"][0]

    reviewed = await client.post(
        f"/api/v1/legal/change-radar/runs/{created.json()['id']}/review",
        json={"decision": "accepted", "reason": "Verified against the cited source versions."},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review"]["decision"] == "accepted"
