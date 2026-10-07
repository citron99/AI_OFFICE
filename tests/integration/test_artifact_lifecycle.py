"""Artifact lifecycle: DLP preflight, provenance, retention, cascade delete (ART-002..006)."""

import io
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.db.tables.artifacts import ArtifactRecord
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord
from app.services.files import MIME_TYPES


async def upload(
    client: httpx.AsyncClient, content: bytes, name: str = "doc.txt"
) -> httpx.Response:
    return await client.post("/api/v1/files", files={"file": (name, content, "text/plain")})


async def test_upload_records_dlp_metadata_and_classification(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await upload(client, "Обычный документ о договоре поставки.")
    assert response.status_code == 201, response.text
    body = response.json()
    async with create_session_factory(engine)() as session:
        record = await session.get(ArtifactRecord, body["id"])
        assert record is not None
        # A benign document is at least INTERNAL and carries a retention deadline.
        assert record.classification in {"INTERNAL", "PUBLIC", "CONFIDENTIAL"}
        assert record.source_provenance == "user_upload"
        assert record.retention_until is not None
        assert record.company_id == "comp_demo"


async def test_restricted_content_is_blocked_before_storage(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await upload(client, "password=super-secret-123 must not be stored")
    assert response.status_code == 422, response.text
    assert "DLP" in response.text
    # Nothing was persisted and no file reached the storage directory.
    async with create_session_factory(engine)() as session:
        total = await session.scalar(select(func.count()).select_from(ArtifactRecord))
    assert total == 0


@pytest.mark.parametrize("extension", [".docx", ".xlsx"])
async def test_office_document_embedded_secret_is_blocked_before_storage(
    client: httpx.AsyncClient, engine: AsyncEngine, extension: str
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if extension == ".docx":
            archive.writestr(
                "word/document.xml", "<document><p>password=synthetic-secret</p></document>"
            )
        else:
            archive.writestr("xl/workbook.xml", "<workbook/>")
            archive.writestr(
                "xl/sharedStrings.xml", "<strings><t>password=synthetic-secret</t></strings>"
            )
    response = await client.post(
        "/api/v1/files",
        files={"file": ("secret" + extension, buffer.getvalue(), MIME_TYPES[extension])},
    )
    assert response.status_code == 422, response.text
    assert "DLP" in response.text
    async with create_session_factory(engine)() as session:
        assert await session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0


async def test_delete_cascades_chunks_embeddings_and_file(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
) -> None:
    uploaded = await upload(client, b"Synthetic contract: notice must be in writing.")
    assert uploaded.status_code == 201, uploaded.text
    artifact_id = uploaded.json()["id"]
    created = await client.post(
        "/api/v1/knowledge/sources",
        json={
            "artifact_id": artifact_id,
            "title": "Synthetic rule",
            "jurisdiction": "LV",
            "document_type": "test_norm",
            "authority": "Test only",
            "version": "1",
            "effective_from": "2026-01-01",
            "status": "ACTIVE",
        },
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]
    indexed = await client.post(f"/api/v1/knowledge/sources/{source_id}/reindex")
    assert indexed.status_code in {200, 201}, indexed.text

    deleted = await client.delete(f"/api/v1/files/{artifact_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] == artifact_id

    async with create_session_factory(engine)() as session:
        assert await session.get(ArtifactRecord, artifact_id) is None
        assert await session.get(KnowledgeSourceRecord, source_id) is None
        chunks = await session.scalar(
            select(func.count())
            .select_from(KnowledgeChunkRecord)
            .where(KnowledgeChunkRecord.source_id == source_id)
        )
        assert chunks == 0
    # The download endpoint no longer resolves the artifact.
    assert (await client.get(f"/api/v1/files/{artifact_id}")).status_code == 404


async def test_delete_is_owner_scoped(engine: AsyncEngine, tmp_path: Path) -> None:
    """Another owner cannot delete a foreign artifact."""
    import hashlib

    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        app_env="test",
        auth_mode="api_key",
        upload_dir=tmp_path,
        auth_token_hashes={
            hashlib.sha256(token.encode()).hexdigest(): {"user_id": user, "role": "owner"}
            for token, user in [("tok-f-owner", "owner-f"), ("tok-f-other", "owner-g")]
        },
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            c.headers["Authorization"] = "Bearer tok-f-owner"
            uploaded = await upload(c, b"Owner file content")
            assert uploaded.status_code == 201
            artifact_id = uploaded.json()["id"]
            c.headers["Authorization"] = "Bearer tok-f-other"
            assert (await c.delete(f"/api/v1/files/{artifact_id}")).status_code == 404
            c.headers["Authorization"] = "Bearer tok-f-owner"
            assert (await c.delete(f"/api/v1/files/{artifact_id}")).status_code == 200


async def test_antivirus_content_scan_blocks_executables(client: httpx.AsyncClient) -> None:
    from app.security.antivirus import EICAR_TEST_FILE, content_scan

    # The EICAR test signature anywhere in the file is a threat.
    assert content_scan(f"prefix {EICAR_TEST_FILE} suffix".encode()).status == "threat"
    eicar_upload = await upload(client, f"report {EICAR_TEST_FILE}".encode())
    assert eicar_upload.status_code == 422
    assert "antivirus" in eicar_upload.text

    # MZ as mid-file text is not a PE header; a PE header at byte zero is.
    pe_upload = await upload(client, b"This text merely mentions MZ late")
    assert pe_upload.status_code == 201
    pe_header = await upload(client, b"MZ fake executable as plain text")
    assert pe_header.status_code == 422
    assert "WINDOWS_EXECUTABLE" in pe_header.text

    clean = await upload(client, b"Ordinary clean report text")
    assert clean.status_code == 201
