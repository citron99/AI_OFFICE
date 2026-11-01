import asyncio
import hashlib

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import ArtifactNotFoundError, FileValidationError
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord
from app.knowledge.embeddings import (
    RETRIEVAL_VERSION,
    EmbeddingProvider,
    tokens,
    validate_vector,
)
from app.knowledge.local_embeddings import create_embedding_provider
from app.knowledge.parser import chunk_document, parse_document
from app.knowledge.splitting import split_chunks, split_for_provider
from app.models.knowledge import (
    SearchHit,
    SearchRequest,
    SearchResponse,
    SourceCreate,
    SourceResponse,
)
from app.security.data_classification import ClassificationResult, DataClass, classify_text
from app.services.files import FileService

# Server-side pilot policy. Never accept this list from a search request.
PILOT_CLASSIFICATIONS = frozenset({"PUBLIC", "INTERNAL"})
MAX_SEARCH_CANDIDATES = 5000

# Source classification domain in the pilot has no PERSONAL tier; personal
# hits fail closed to CONFIDENTIAL so the retrieval gate blocks them.
_SOURCE_CLASS_BY_DATA_CLASS: dict[DataClass, str] = {
    DataClass.PUBLIC: "PUBLIC",
    DataClass.INTERNAL: "INTERNAL",
    DataClass.CONFIDENTIAL: "CONFIDENTIAL",
    DataClass.PERSONAL: "CONFIDENTIAL",
    DataClass.RESTRICTED: "RESTRICTED",
}
_SOURCE_CLASS_SEVERITY: dict[str, int] = {
    "PUBLIC": 0,
    "INTERNAL": 1,
    "CONFIDENTIAL": 2,
    "RESTRICTED": 3,
}


def _artifact_class_as_source_class(value: str) -> str:
    """Project the artifact label (which may be PERSONAL) into the source domain."""
    if value == DataClass.PERSONAL.value.upper():
        return "CONFIDENTIAL"
    return value if value in _SOURCE_CLASS_SEVERITY else "PUBLIC"


def _stricter(left: str, right: str) -> str:
    return left if _SOURCE_CLASS_SEVERITY[left] >= _SOURCE_CLASS_SEVERITY[right] else right


class KnowledgeService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        embeddings: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.embeddings = embeddings or create_embedding_provider(settings)
        if not 1 <= self.embeddings.dimensions <= 4096 or len(self.embeddings.model_id) > 100:
            raise ValueError("Invalid embedding provider identity or dimensions")

    @property
    def retrieval_version(self) -> str:
        return "semantic-cosine-v1" if self.embeddings.semantic else RETRIEVAL_VERSION

    def _embed(self, text: str) -> list[float]:
        try:
            return validate_vector(
                self.embeddings.embed(text),
                self.embeddings.dimensions,
                allow_zero=not self.embeddings.semantic,
            )
        except Exception as exc:
            raise FileValidationError(
                "EMBEDDING_INVALID: embedding failed or text exceeds model limits"
            ) from exc

    def prepare_queries(self, texts: list[str], *, max_queries: int = 64) -> list[str]:
        queries: list[str] = []
        for text in texts:
            # Keep within SearchRequest's character bound before token subdivision.
            for offset in range(0, len(text), 8000):
                queries.extend(
                    split_for_provider(
                        text[offset : offset + 8000],
                        self.embeddings,
                        max_parts=max_queries - len(queries),
                    )
                )
        return queries

    def _response(self, hits: list[SearchHit]) -> SearchResponse:
        warnings = (
            ["SEMANTIC_PILOT: model relevance and score threshold require independent evaluation."]
            if self.embeddings.semantic
            else [
                "MOCK_EMBEDDINGS: lexical-gated token-hash ranking is not semantic legal retrieval."
            ]
        )
        return SearchResponse(
            hits=hits,
            embedding_model=self.embeddings.model_id,
            retrieval_version=self.retrieval_version,
            embedding_dimensions=self.embeddings.dimensions,
            warnings=warnings,
        )

    async def reindex(
        self,
        source_id: str,
        *,
        owner_id: str,
        company_id: str,
    ) -> SourceResponse:
        source = await self.session.get(KnowledgeSourceRecord, source_id)
        if source is None or source.owner_id != owner_id or source.company_id != company_id:
            raise ArtifactNotFoundError(source_id)
        if (
            source.embedding_model == self.embeddings.model_id
            and source.embedding_dimensions == self.embeddings.dimensions
        ):
            return SourceResponse.model_validate(source)
        existing = await self._find_reindex(source_id, owner_id, company_id)
        if existing is not None:
            return SourceResponse.model_validate(existing)
        artifact, _ = await FileService(self.session, self.settings).get(
            source.artifact_id,
            owner_id=owner_id,
            company_id=company_id,
        )
        if artifact.sha256 != source.sha256:
            raise FileValidationError(
                "Source artifact hash changed; cannot reindex historical source"
            )
        payload = SourceCreate.model_validate(
            {name: getattr(source, name) for name in SourceCreate.model_fields}
        )
        # A new source preserves all historical source/chunk IDs and their citations.
        try:
            return await self._ingest(
                payload,
                owner_id=owner_id,
                company_id=company_id,
                reindex_of_id=source_id,
            )
        except IntegrityError:
            # _ingest rolled back. A concurrent request may have published this target.
            winner = await self._find_reindex(source_id, owner_id, company_id)
            if winner is None:
                raise
            return SourceResponse.model_validate(winner)

    async def _find_reindex(
        self,
        source_id: str,
        owner_id: str,
        company_id: str,
    ) -> KnowledgeSourceRecord | None:
        result = await self.session.scalars(
            select(KnowledgeSourceRecord).where(
                KnowledgeSourceRecord.reindex_of_id == source_id,
                KnowledgeSourceRecord.owner_id == owner_id,
                KnowledgeSourceRecord.company_id == company_id,
                KnowledgeSourceRecord.embedding_model == self.embeddings.model_id,
                KnowledgeSourceRecord.embedding_dimensions == self.embeddings.dimensions,
            )
        )
        return result.first()

    async def ingest(
        self,
        payload: SourceCreate,
        *,
        owner_id: str,
        company_id: str,
    ) -> SourceResponse:
        return await self._ingest(
            payload,
            owner_id=owner_id,
            company_id=company_id,
        )

    async def _ingest(
        self,
        payload: SourceCreate,
        *,
        owner_id: str,
        company_id: str,
        reindex_of_id: str | None = None,
    ) -> SourceResponse:
        artifact, path = await FileService(self.session, self.settings).get(
            payload.artifact_id,
            owner_id=owner_id,
            company_id=company_id,
        )

        def extract() -> list[tuple[str, str, int | None, str | None, list[float]]]:
            with path.open("rb") as stream:
                data = stream.read(self.settings.max_upload_bytes + 1)
            if len(data) > self.settings.max_upload_bytes:
                raise FileValidationError("Stored file exceeds upload limit")
            if hashlib.sha256(data).hexdigest() != artifact.sha256:
                raise FileValidationError("Stored file hash mismatch")
            chunks = chunk_document(parse_document(artifact.filename, artifact.mime_type, data))
            chunks = split_chunks(chunks, self.embeddings)
            return [(c.text, c.locator, c.page, c.article, self._embed(c.text)) for c in chunks]

        chunks = await asyncio.to_thread(extract)
        # Second DLP boundary: the upload scanner only saw the container bytes,
        # compressed streams can hide secrets. Re-scan the extracted text before
        # a single chunk reaches the index (audit п.7).
        extracted_text = "\n\n".join(text for text, *_rest in chunks)
        post_extraction: ClassificationResult = classify_text(extracted_text)
        if post_extraction.data_class == DataClass.RESTRICTED:
            rules = sorted({finding.rule for finding in post_extraction.findings})
            artifact.classification = DataClass.RESTRICTED.value.upper()
            artifact.dlp_rules = rules
            await self.session.commit()
            raise FileValidationError(
                "Post-extraction DLP refused the source: restricted data detected ("
                + ",".join(rules)
                + ")"
            )
        # The strictest of {client label, stored upload verdict, extraction verdict}
        # wins, so a client cannot loosen a server classification by re-declaring
        # the label on the source payload.
        server_classification = _stricter(
            payload.classification,
            _stricter(
                _artifact_class_as_source_class(artifact.classification),
                _SOURCE_CLASS_BY_DATA_CLASS[post_extraction.data_class],
            ),
        )
        if post_extraction.findings:
            artifact.dlp_rules = sorted(
                set(artifact.dlp_rules or [])
                | {finding.rule for finding in post_extraction.findings}
            )
        if (
            _SOURCE_CLASS_SEVERITY[server_classification]
            > _SOURCE_CLASS_SEVERITY[_artifact_class_as_source_class(artifact.classification)]
        ):
            artifact.classification = server_classification
        source_payload = payload.model_copy(update={"classification": server_classification})
        source = KnowledgeSourceRecord(
            **source_payload.model_dump(),
            company_id=company_id,
            owner_id=owner_id,
            sha256=artifact.sha256,
            embedding_model=self.embeddings.model_id,
            embedding_dimensions=self.embeddings.dimensions,
            chunk_count=len(chunks),
            reindex_of_id=reindex_of_id,
        )
        try:
            self.session.add(source)
            await self.session.flush()
            self.session.add_all(
                [
                    KnowledgeChunkRecord(
                        source_id=source.id,
                        ordinal=number,
                        text=text,
                        locator=locator,
                        page=page,
                        article=article,
                        embedding=vector,
                    )
                    for number, (text, locator, page, article, vector) in enumerate(chunks)
                ]
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return SourceResponse.model_validate(source)

    async def search(
        self,
        payload: SearchRequest,
        *,
        owner_id: str,
        company_id: str,
    ) -> SearchResponse:
        source = KnowledgeSourceRecord
        chunk = KnowledgeChunkRecord
        # All access, provenance and temporal filters happen in SQL BEFORE text is loaded.
        statement = (
            select(source, chunk)
            .join(chunk, chunk.source_id == source.id)
            .where(
                source.owner_id == owner_id,
                source.company_id == company_id,
                source.classification.in_(PILOT_CLASSIFICATIONS),
                source.jurisdiction == payload.jurisdiction,
                source.status == "ACTIVE",
                source.effective_from <= payload.effective_on,
                or_(source.effective_to.is_(None), source.effective_to >= payload.effective_on),
                source.embedding_model == self.embeddings.model_id,
                source.embedding_dimensions == self.embeddings.dimensions,
            )
        )
        if payload.document_types:
            statement = statement.where(source.document_type.in_(payload.document_types))
        vector = await asyncio.to_thread(self._embed, payload.query)
        query_tokens = set(tokens(payload.query))
        if not any(vector):
            return self._response([])
        if self.session.get_bind().dialect.name == "postgresql":
            # CASE protects mixed-dimension rows regardless of SQL planner predicate order.
            distance = case(
                (
                    and_(
                        source.embedding_model == self.embeddings.model_id,
                        source.embedding_dimensions == self.embeddings.dimensions,
                        func.vector_dims(chunk.embedding) == self.embeddings.dimensions,
                    ),
                    chunk.embedding.cosine_distance(vector),
                ),
                else_=None,
            )
            statement = (
                statement.where(distance < 0.999999)
                .order_by(distance, source.id, chunk.ordinal)
                .limit(MAX_SEARCH_CANDIDATES + 1)
            )
        else:
            # SQLite is a bounded test backend, not a production vector search engine.
            statement = statement.order_by(source.id, chunk.ordinal).limit(
                MAX_SEARCH_CANDIDATES + 1
            )
        rows = (await self.session.execute(statement)).all()
        if len(rows) > MAX_SEARCH_CANDIDATES:
            raise FileValidationError(
                "Pilot search candidate limit exceeded; narrow document_types"
            )
        hits: list[SearchHit] = []
        for record, part in rows:
            # Hash collisions alone are not evidence of even lexical relevance.
            # Apply before top-k so rejected candidates cannot displace valid hits.
            if not self.embeddings.semantic and not query_tokens.intersection(tokens(part.text)):
                continue
            stored = validate_vector(
                list(part.embedding),
                self.embeddings.dimensions,
                allow_zero=not self.embeddings.semantic,
            )
            score = sum(a * b for a, b in zip(vector, stored, strict=True))
            if score <= (
                self.settings.semantic_min_score if self.embeddings.semantic else 0.000001
            ):
                continue
            hits.append(
                SearchHit(
                    source_id=record.id,
                    chunk_id=part.id,
                    title=record.title,
                    version=record.version,
                    jurisdiction=record.jurisdiction,
                    document_type=record.document_type,
                    authority=record.authority,
                    effective_from=record.effective_from,
                    effective_to=record.effective_to,
                    text=part.text,
                    locator=part.locator,
                    page=part.page,
                    article=part.article,
                    score=min(1.0, max(0.0, score)),
                )
            )
        hits.sort(key=lambda hit: -hit.score)
        response = self._response(hits[: payload.top_k])
        # LEG-007 freshness policy: flag hits whose RAG cache entry predates
        # the configured window. A warning, never a silent substitution.
        max_age = self.settings.legal_rag_max_source_age_days
        if max_age and hits:
            from datetime import UTC, datetime, timedelta

            cutoff = datetime.now(UTC) - timedelta(days=max_age)
            stale_ids = {
                record.id
                for record, _part in rows
                if record.id in {hit.source_id for hit in response.hits}
                and (
                    record.indexed_at.replace(tzinfo=UTC)
                    if record.indexed_at.tzinfo is None
                    else record.indexed_at
                )
                < cutoff
            }
            if stale_ids:
                response.warnings.append(
                    f"STALE_SOURCE: {len(stale_ids)} источник(ов) проиндексированы "
                    f"ранее окна свежести ({max_age} дн.); подтвердите актуальность "
                    "в КонсультантПлюс перед выводом."
                )
        return response
