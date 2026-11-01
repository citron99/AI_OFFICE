"""DLP verdict, not the request body, decides a knowledge source's classification.

Covers п.7 of the audit: the retrieval gate read a client-supplied label and the
extracted text was never re-scanned, so content that only becomes visible after
parsing was indexed as plaintext under a PUBLIC/INTERNAL label.
"""

import zlib

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.db.tables.artifacts import ArtifactRecord
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord

PDF_SECRET = "Payment clause. password=Sup3rS3cretX applies."


def pdf_with(draw_text: str) -> bytes:
    """One-page PDF whose text lives in a Flate stream, so raw-byte DLP is blind."""
    content = f"BT /F1 12 Tf 72 720 Td ({draw_text}) Tj ET".encode()
    stream = zlib.compress(content, 9)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" /Filter /FlateDecode >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


async def upload(client: httpx.AsyncClient, filename: str, mime_type: str, data: bytes) -> str:
    response = await client.post("/api/v1/files", files={"file": (filename, data, mime_type)})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


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


async def counts(engine: AsyncEngine) -> tuple[int, int]:
    async with create_session_factory(engine)() as session:
        sources = await session.scalar(select(func.count()).select_from(KnowledgeSourceRecord))
        chunks = await session.scalar(select(func.count()).select_from(KnowledgeChunkRecord))
    return int(sources or 0), int(chunks or 0)


async def test_secret_only_visible_after_pdf_extraction_is_refused(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """Extraction is a second DLP boundary: a stored secret must never reach the index."""
    artifact_id = await upload(client, "synthetic.pdf", "application/pdf", pdf_with(PDF_SECRET))
    async with create_session_factory(engine)() as session:
        artifact = await session.get(ArtifactRecord, artifact_id)
        assert artifact is not None
        # The upload scan only sees compressed bytes; that is the gap being closed.
        assert artifact.classification == "PUBLIC"

    response = await client.post("/api/v1/knowledge/sources", json=source_payload(artifact_id))
    assert response.status_code == 422, response.text
    assert "restricted" in response.json()["message"].lower()
    assert await counts(engine) == (0, 0)

    async with create_session_factory(engine)() as session:
        artifact = await session.get(ArtifactRecord, artifact_id)
        assert artifact is not None
        assert artifact.classification == "RESTRICTED"
        assert "password_assignment" in artifact.dlp_rules


async def test_client_label_cannot_loosen_a_stricter_server_verdict(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """Declaring PUBLIC over a CONFIDENTIAL artifact neither lies nor retrieves."""
    artifact_id = await upload(
        client, "contract.txt", "text/plain", "Договор № LV-001 о поставке зерна".encode()
    )
    response = await client.post(
        "/api/v1/knowledge/sources", json=source_payload(artifact_id, classification="PUBLIC")
    )
    assert response.status_code == 201, response.text
    assert response.json()["classification"] == "CONFIDENTIAL"

    search = await client.post("/api/v1/knowledge/search", json=query())
    assert search.status_code == 200
    assert search.json()["hits"] == []
    sources, _ = await counts(engine)
    assert sources == 1


async def test_personal_data_is_not_pilot_retrievable(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """PERSONAL has no place in the source label domain, so it fails closed."""
    artifact_id = await upload(
        client, "notice.txt", "text/plain", b"Write to legal@example.com about payment."
    )
    response = await client.post(
        "/api/v1/knowledge/sources", json=source_payload(artifact_id, classification="PUBLIC")
    )
    assert response.status_code == 201, response.text
    assert response.json()["classification"] == "CONFIDENTIAL"
    search = await client.post("/api/v1/knowledge/search", json=query())
    assert search.json()["hits"] == []


async def test_clean_source_keeps_the_declared_pilot_label(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """A stricter-or-equal declaration still wins: the pilot corpus stays usable."""
    artifact_id = await upload(client, "rule.txt", "text/plain", b"Article 1\nPayment terms.")
    response = await client.post(
        "/api/v1/knowledge/sources", json=source_payload(artifact_id, classification="INTERNAL")
    )
    assert response.status_code == 201, response.text
    assert response.json()["classification"] == "INTERNAL"
    search = await client.post("/api/v1/knowledge/search", json=query())
    assert [hit["source_id"] for hit in search.json()["hits"]] == [response.json()["id"]]
