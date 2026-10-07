import asyncio
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from app.core.exceptions import FileValidationError
from app.core.security import detections
from app.db.tables.artifacts import ArtifactRecord
from app.knowledge.parser import chunk_document, parse_document
from app.llm.base import LLMProvider
from app.llm.telemetry import tracked_generate
from app.models.agent import Citation, Finding
from app.models.enums import RiskLevel
from app.models.legal import DocumentExcerpt, EvidenceAssessment, LegalDraft, LegalResult
from app.prompts.legal import (
    EVIDENCE_ASSESSMENT_PROMPT,
    EVIDENCE_ASSESSMENT_VERSION,
    LEGAL_SYSTEM_PROMPT,
)
from app.security.egress_gateway import EgressRequest, evaluate_egress
from app.services.files import FileService
from app.services.knowledge import PILOT_CLASSIFICATIONS, KnowledgeService


async def extract_attachments(
    knowledge: KnowledgeService,
    artifact_ids: list[str],
    user_id: str,
    company_id: str,
) -> list[DocumentExcerpt]:
    if len(artifact_ids) > 10:
        raise FileValidationError("At most 10 attachments are supported")
    excerpts: list[DocumentExcerpt] = []
    total = 0
    for artifact_id in dict.fromkeys(artifact_ids):
        artifact, path = await FileService(knowledge.session, knowledge.settings).get(
            artifact_id,
            owner_id=user_id,
            company_id=company_id,
        )
        if artifact.classification not in PILOT_CLASSIFICATIONS:
            raise FileValidationError("Attachment classification is not allowed in legal context")

        def extract(
            artifact: ArtifactRecord = artifact, path: Path = path
        ) -> list[DocumentExcerpt]:
            with path.open("rb") as stream:
                data = stream.read(knowledge.settings.max_upload_bytes + 1)
            if len(data) > knowledge.settings.max_upload_bytes:
                raise FileValidationError("Stored attachment exceeds size limit")
            if hashlib.sha256(data).hexdigest() != artifact.sha256:
                raise FileValidationError("Stored attachment hash mismatch")
            blocks = parse_document(artifact.filename, artifact.mime_type, data)
            return [
                DocumentExcerpt(
                    excerpt_id=f"{artifact.id}:{number}",
                    artifact_id=artifact.id,
                    filename=artifact.filename,
                    sha256=artifact.sha256,
                    locator=part.locator,
                    text=part.text,
                )
                for number, part in enumerate(chunk_document(blocks))
            ]

        parts = await asyncio.to_thread(extract)
        total += sum(len(part.text) for part in parts)
        if total > knowledge.settings.legal_document_max_chars:
            # Never silently truncate a contract and present a partial review as complete.
            raise FileValidationError("Legal attachment context exceeds limit; split documents")
        excerpts.extend(parts)
    return excerpts


def validate_draft(draft: LegalDraft, result: LegalResult) -> list[Finding]:
    sources = {hit.chunk_id: hit for hit in result.evidence}
    documents = {part.excerpt_id: part for part in result.documents}
    findings = []
    for index, item in enumerate(draft.findings, 1):
        kinds = {ref.kind for ref in item.references}
        if "source" not in kinds or (documents and "document" not in kinds):
            raise ValueError("Each finding needs source evidence and reviewed document evidence")
        citations: list[Citation] = []
        for ref in item.references:
            if not ref.quote.strip() or len(ref.quote.strip()) < 8:
                raise ValueError("Unusable quote")
            if ref.kind == "source":
                hit = sources.get(ref.reference_id)
                if hit is None or ref.quote not in hit.text:
                    raise ValueError("Unknown source or non-verbatim quote")
                citations.append(
                    Citation(
                        source_id=hit.source_id,
                        title=hit.title,
                        locator=hit.locator,
                        version=hit.version,
                        jurisdiction=hit.jurisdiction,
                    )
                )
            else:
                part = documents.get(ref.reference_id)
                if part is None or ref.quote not in part.text:
                    raise ValueError("Unknown document or non-verbatim quote")
                citations.append(
                    Citation(source_id=part.artifact_id, title=part.filename, locator=part.locator)
                )
        findings.append(
            Finding(
                code=f"LEGAL_DRAFT_{index}",
                title=item.title,
                description=item.description,
                risk_level=item.risk_level,
                citations=citations,
            )
        )
    return findings


def validate_assessment(assessment: EvidenceAssessment, result: LegalResult) -> None:
    if not assessment.rationale.strip():
        raise ValueError("Assessment rationale is empty")
    if any(not item.strip() or len(item) > 1000 for item in assessment.missing_information):
        raise ValueError("Invalid missing information")
    if assessment.status == "sufficient":
        if not assessment.references or assessment.missing_information:
            raise ValueError("Sufficient assessment needs sources and no missing information")
    elif not assessment.missing_information:
        raise ValueError("Insufficient assessment must explain what is missing")
    sources = {hit.chunk_id: hit for hit in result.evidence}
    for ref in assessment.references:
        hit = sources.get(ref.reference_id)
        if (
            ref.kind != "source"
            or hit is None
            or len(ref.quote.strip()) < 8
            or ref.quote not in hit.text
        ):
            raise ValueError("Invalid assessment source reference")


async def analyze(
    provider: LLMProvider,
    result: LegalResult,
    *,
    query: str,
    model_id: str,
    timeout_seconds: float,
) -> LegalResult:
    if any(
        detections(text)
        for text in [
            query,
            *(hit.text for hit in result.evidence),
            *(part.text for part in result.documents),
        ]
    ):
        result.status = "analysis_blocked"
        result.summary = "Внешний анализ заблокирован: обнаружены чувствительные данные."
        result.warnings.append("SENSITIVE_DATA_BLOCK: провайдер не вызывался.")
        return result
    result.analysis_attempted = True
    result.mode = "legal_analysis_pilot"
    result.analysis_model = model_id
    result.evidence_assessment_version = EVIDENCE_ASSESSMENT_VERSION
    # Fail closed even if this helper is called with a previously populated result.
    result.findings = []
    result.verified_references = []
    result.evidence_assessment = None
    if model_id == "mock":
        result.warnings.append(
            "MOCK_ANALYSIS: ответ тестового провайдера, не реальное LLM-заключение."
        )
    payload = {
        "request": query,
        "jurisdiction": result.jurisdiction,
        "effective_on": result.effective_on.isoformat() if result.effective_on else None,
        "sources": [hit.model_dump(mode="json") for hit in result.evidence],
        "documents": [part.model_dump(mode="json") for part in result.documents],
    }
    if model_id != "mock":
        # TZ 10.3: the egress gateway is the last gate before an external call;
        # confidential and personal classes require contours the MVP lacks.
        verdict = evaluate_egress(
            EgressRequest(
                company_id="system",
                route="external_llm",
                purpose="legal_analysis",
                content=json.dumps(payload, ensure_ascii=False, default=str),
            )
        )
        if verdict.decision == "block":
            result.status = "analysis_blocked"
            result.summary = "Внешний вызов заблокирован Data Egress Gateway."
            result.warnings.append(f"EGRESS_BLOCKED: {','.join(verdict.reasons)}")
            return result
    try:
        # One budget covers both calls; the preflight cannot double the configured timeout.
        async with asyncio.timeout(timeout_seconds):
            assessment = await tracked_generate(
                provider,
                records=result.model_calls,
                system_prompt=EVIDENCE_ASSESSMENT_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                response_model=EvidenceAssessment,
            )
            assessment = EvidenceAssessment.model_validate(assessment.model_dump())
            validate_assessment(assessment, result)
            result.evidence_assessment = assessment
            result.warnings.append(
                "SUFFICIENCY_MODEL_JUDGEMENT: достаточность оценена моделью, "
                "не подтверждена независимой юридической проверкой."
            )
            if assessment.status != "sufficient":
                result.status = "insufficient_evidence"
                result.summary = (
                    "Найденных фрагментов недостаточно для полного ответа. "
                    "Генерация юридических выводов не запускалась."
                )
                result.unresolved_questions.extend(assessment.missing_information)
                result.recommended_actions = ["Дополните источники и передайте вопрос специалисту."]
                return result
            draft = await tracked_generate(
                provider,
                records=result.model_calls,
                system_prompt=LEGAL_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                response_model=LegalDraft,
            )
        # Revalidate even when a provider returns a preconstructed model instance.
        draft = LegalDraft.model_validate(draft.model_dump())
        findings = validate_draft(draft, result)
    except (ValidationError, ValueError):
        result.status = "analysis_rejected"
        result.summary = "LLM-ответ отклонён: оценка достаточности, схема или цитаты неверны."
        result.warnings.append("LEGAL_EVIDENCE_INVALID: неподтверждённый ответ не опубликован.")
        return result
    except Exception:
        # Do not expose provider exceptions, prompts, credentials, or a partial response.
        result.status = "analysis_unavailable"
        result.summary = "Анализ недоступен; юридические выводы не сделаны."
        result.warnings.append("LEGAL_PROVIDER_UNAVAILABLE: ошибка или тайм-аут провайдера.")
        return result
    result.findings = findings
    result.verified_references = [ref for item in draft.findings for ref in item.references]
    result.status = "draft_analysis" if findings else "insufficient_evidence"
    result.summary = (
        "Подготовлен черновик анализа. Цитаты проверены по тексту; выводы должен проверить юрист."
        if findings
        else "Подтверждённых замечаний нет; это не означает отсутствие юридических рисков."
    )
    result.warnings.append(
        "Проверено наличие цитат, а не юридическая обоснованность выводов. Требуется специалист."
    )
    if any(f.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} for f in findings):
        result.warnings.append("HIGH_RISK_REVIEW_REQUIRED: не действуйте без проверки юристом.")
    return result
