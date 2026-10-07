import asyncio
import hashlib
import io
import re
import zipfile
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4
from xml.etree import ElementTree

from fastapi import UploadFile
from sqlalchemy import CursorResult, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import ArtifactNotFoundError, FileValidationError
from app.db.tables.artifacts import ArtifactRecord
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord
from app.security.antivirus import content_scan
from app.security.data_classification import (
    DataClass,
    classify_text,
)
from app.storage import LocalDirectoryStorage, ObjectStorage
from app.storage.factory import create_storage

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_MAX_OFFICE_SCAN_BYTES = 20 * 1024 * 1024


def _office_scan_text(data: bytes) -> str:
    """Extract bounded visible XML text before DLP decides whether to store it."""
    parts: list[str] = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for entry in archive.infolist():
                if not entry.filename.lower().endswith((".xml", ".rels")):
                    continue
                total += entry.file_size
                if total > _MAX_OFFICE_SCAN_BYTES:
                    raise FileValidationError("Office text exceeds DLP inspection limit")
                content = archive.read(entry)
                if b"<!doctype" in content.lower() or b"<!entity" in content.lower():
                    raise FileValidationError("Office XML declarations are not accepted")
                parts.append("".join(ElementTree.fromstring(content).itertext()))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, ElementTree.ParseError) as exc:
        raise FileValidationError("Office content cannot be inspected by DLP") from exc
    return "\n".join(parts)


def validate_file(filename: str, mime_type: str | None, data: bytes) -> str:
    if not filename or len(filename) > 255 or any(ord(c) < 32 for c in filename):
        raise FileValidationError("Invalid filename")
    if "/" in filename or "\\" in filename or ":" in filename:
        raise FileValidationError("Filename must not contain a path")
    extension = Path(filename).suffix.lower()
    expected = MIME_TYPES.get(extension)
    if expected is None:
        raise FileValidationError("Only PDF, DOCX, TXT, CSV and XLSX are supported")
    supplied = (mime_type or "").split(";", 1)[0].strip().lower()
    if supplied != expected:
        raise FileValidationError("MIME type does not match the filename")
    if not data:
        raise FileValidationError("Empty files are not accepted")
    if extension == ".pdf" and not data.startswith(b"%PDF-"):
        raise FileValidationError("Invalid PDF signature")
    if extension in {".txt", ".csv"}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise FileValidationError("Text files must use UTF-8") from exc
        if "\x00" in text:
            raise FileValidationError("Binary content in text file")
    if extension in {".docx", ".xlsx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                names = {entry.filename for entry in entries}
                required = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
                if "[Content_Types].xml" not in names or required not in names:
                    raise FileValidationError("Invalid Office document structure")
                if len(entries) > 2000 or sum(e.file_size for e in entries) > 100 * 1024 * 1024:
                    raise FileValidationError("Office archive exceeds expansion limits")
                if any("vbaproject" in name.lower() for name in names):
                    raise FileValidationError("Macro-enabled documents are not accepted")
        except zipfile.BadZipFile as exc:
            raise FileValidationError("Invalid Office archive") from exc
    return expected


class FileService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        storage: ObjectStorage | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        # Default resolves from settings, so knowledge/legal paths pick the
        # same backend even without explicit injection.
        self.storage: ObjectStorage = storage if storage is not None else create_storage(settings)

    async def upload(self, upload: UploadFile, *, owner_id: str, company_id: str) -> ArtifactRecord:
        try:
            data = await upload.read(self.settings.max_upload_bytes + 1)
        finally:
            await upload.close()
        if len(data) > self.settings.max_upload_bytes:
            raise FileValidationError("File exceeds upload size limit")
        filename = upload.filename or ""
        mime_type = validate_file(filename, upload.content_type, data)
        # ART-002: DLP preflight runs before indexing or storage decisions.
        # Compressed Office XML must be extracted; decoding ZIP bytes misses it.
        scan_text = (
            _office_scan_text(data)
            if Path(filename).suffix.lower() in {".docx", ".xlsx"}
            else data.decode("utf-8", errors="ignore")
        )
        classification = classify_text(scan_text)
        if classification.data_class == DataClass.RESTRICTED:
            # TZ 10.2: RESTRICTED content is an immediate deny, nothing stored.
            rules = ",".join(sorted({f.rule for f in classification.findings}))
            raise FileValidationError(f"Upload blocked by DLP: restricted data detected ({rules})")
        # ART-002: content antivirus scan after DLP, still before storage.
        av = content_scan(data)
        if av.status == "threat":
            raise FileValidationError(f"Upload blocked by antivirus scan: {','.join(av.threats)}")
        storage_key = uuid4().hex
        object_key = self._namespaced(company_id, storage_key)
        record = ArtifactRecord(
            company_id=company_id,
            owner_id=owner_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            storage_key=storage_key,
            classification=classification.data_class.value.upper(),
            source_provenance="user_upload",
            retention_until=datetime.now(UTC)
            + timedelta(days=self.settings.artifact_retention_days),
            dlp_rules=sorted({f.rule for f in classification.findings}),
        )

        try:
            await asyncio.to_thread(self.storage.put, object_key, data)
            self.session.add(record)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            # Compensate through the selected backend. This covers both the
            # company subdirectory of local storage and S3/MinIO objects.
            with suppress(Exception):
                await asyncio.to_thread(self.storage.delete, object_key)
            raise
        return record

    async def delete(self, artifact_id: str, *, owner_id: str, company_id: str) -> int:
        """ART-006: the source deletion removes chunks, embeddings and the file."""
        record = await self.session.get(ArtifactRecord, artifact_id)
        if record is None or record.owner_id != owner_id or record.company_id != company_id:
            raise ArtifactNotFoundError(artifact_id)
        if not re.fullmatch(r"[0-9a-f]{32}", record.storage_key or ""):
            raise ArtifactNotFoundError(artifact_id)
        object_key = self._namespaced(record.company_id, record.storage_key)
        # Keep a bounded compensation copy until the metadata transaction is
        # durable. Upload limits cap this at MAX_UPLOAD_BYTES.
        backup = await asyncio.to_thread(self.storage.get, object_key)
        await asyncio.to_thread(self.storage.delete, object_key)
        removed_chunks = 0
        try:
            source_result = await self.session.execute(
                select(KnowledgeSourceRecord.id).where(
                    KnowledgeSourceRecord.artifact_id == artifact_id
                )
            )
            source_ids = list(source_result.scalars())
            if source_ids:
                chunk_result = cast(
                    CursorResult[Any],
                    await self.session.execute(
                        sa_delete(KnowledgeChunkRecord)
                        .where(KnowledgeChunkRecord.source_id.in_(source_ids))
                        .execution_options(synchronize_session=False)
                    ),
                )
                removed_chunks = int(chunk_result.rowcount or 0)
                await self.session.execute(
                    sa_delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.id.in_(source_ids))
                )
            await self.session.execute(
                sa_delete(ArtifactRecord).where(ArtifactRecord.id == artifact_id)
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            with suppress(Exception):
                await asyncio.to_thread(self.storage.put, object_key, backup)
            raise
        cache = self._cache_path(record.company_id, record.storage_key)
        if cache is not None:
            await asyncio.to_thread(cache.unlink, True)
        return int(removed_chunks or 0)

    def _namespaced(self, company_id: str, storage_key: str) -> str:
        """TZ 9.5: object keys carry the company namespace."""
        return f"{company_id}/{storage_key}"

    def _cache_path(self, company_id: str | None, storage_key: str) -> Path | None:
        if isinstance(self.storage, LocalDirectoryStorage):
            return None
        namespace = company_id or "unscoped"
        return self.settings.upload_dir.resolve() / "_cache" / namespace / storage_key

    async def materialize(self, record: ArtifactRecord) -> Path:
        """A local path to the bytes, downloading from object storage if needed."""
        if not record.company_id:
            raise ArtifactNotFoundError(record.id)
        if isinstance(self.storage, LocalDirectoryStorage):
            path = self.settings.upload_dir.resolve() / self._namespaced(
                record.company_id, record.storage_key
            )
            if not path.is_file():
                raise ArtifactNotFoundError(record.id)
            return path
        cache = self._cache_path(record.company_id, record.storage_key)
        assert cache is not None
        if not cache.is_file():
            cache.parent.mkdir(parents=True, exist_ok=True)
            data = await asyncio.to_thread(
                self.storage.get, self._namespaced(record.company_id, record.storage_key)
            )
            await asyncio.to_thread(cache.write_bytes, data)
        return cache

    async def get(
        self, artifact_id: str, *, owner_id: str, company_id: str
    ) -> tuple[ArtifactRecord, Path]:
        record = await self.session.get(ArtifactRecord, artifact_id)
        if record is None or record.owner_id != owner_id or record.company_id != company_id:
            raise ArtifactNotFoundError(artifact_id)
        if not re.fullmatch(r"[0-9a-f]{32}", record.storage_key):
            raise ArtifactNotFoundError(artifact_id)
        path = await self.materialize(record)
        return record, path
