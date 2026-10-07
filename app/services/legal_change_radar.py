from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IdempotencyConflictError
from app.db.tables.knowledge import KnowledgeChunkRecord, KnowledgeSourceRecord
from app.db.tables.legal_change import LegalChangeRadarReviewRecord, LegalChangeRadarRunRecord
from app.integrations.consultant_plus.exceptions import (
    ConsultantPlusUnavailableError,
    LicenseScopeExceededError,
)
from app.integrations.consultant_plus.factory import ConsultantPlusProviderLike
from app.models.legal_change import (
    LegalChangeRadarCreate,
    LegalChangeRadarResult,
    LegalChangeRadarRunResponse,
    LegalChangeReviewCreate,
    LegalChangeReviewResponse,
)

HIGH_ATTENTION_TERMS = (
    "штраф",
    "ответственност",
    "неустой",
    "penalty",
    "fine",
    "liability",
    "персональн",
    "personal data",
    "расторжен",
    "termination",
)
REVIEW_TERMS = (
    "обязан",
    "должен",
    "срок",
    "отчет",
    "лиценз",
    "налог",
    "must",
    "shall",
    "deadline",
    "report",
    "licen",
    "tax",
    "payment",
    "оплат",
)


def _request_hash(payload: LegalChangeRadarCreate) -> str:
    raw = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _quote(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:800]


def _signal(before: str, after: str) -> tuple[str, list[str]]:
    value = f"{before} {after}".lower()
    high = sorted({term for term in HIGH_ATTENTION_TERMS if term in value})
    if high:
        return "high_attention", high
    review = sorted({term for term in REVIEW_TERMS if term in value})
    if review:
        return "review", review
    return "informational", []


def _citation(source: KnowledgeSourceRecord, chunk: KnowledgeChunkRecord) -> dict[str, str]:
    return {
        "source_id": source.id,
        "title": source.title,
        "version": source.version,
        "locator": chunk.locator,
        "quote": _quote(chunk.text),
    }


def compare_chunks(
    baseline: KnowledgeSourceRecord,
    current: KnowledgeSourceRecord,
    baseline_chunks: list[KnowledgeChunkRecord],
    current_chunks: list[KnowledgeChunkRecord],
) -> list[dict[str, object]]:
    """Create a deterministic, citation-preserving textual change set.

    Impact levels are triage signals based on explicit terms, not legal conclusions.
    """
    old = {chunk.ordinal: chunk for chunk in baseline_chunks}
    new = {chunk.ordinal: chunk for chunk in current_chunks}
    changes: list[dict[str, object]] = []
    for ordinal in sorted(set(old) | set(new)):
        before = old.get(ordinal)
        after = new.get(ordinal)
        if before and after and _quote(before.text) == _quote(after.text):
            continue
        if before and after:
            ratio = SequenceMatcher(None, _quote(before.text), _quote(after.text)).ratio()
            change_type = "modified"
            summary = f"Section {ordinal + 1} changed; textual similarity {ratio:.0%}."
        elif after:
            change_type = "added"
            summary = f"Section {ordinal + 1} was added."
        else:
            change_type = "removed"
            summary = f"Section {ordinal + 1} was removed."
        before_text = before.text if before else ""
        after_text = after.text if after else ""
        signal, terms = _signal(before_text, after_text)
        changes.append(
            {
                "change_id": f"chg_{ordinal:04d}",
                "change_type": change_type,
                "impact_signal": signal,
                "summary": summary,
                "matched_terms": terms,
                "before": _citation(baseline, before) if before else None,
                "after": _citation(current, after) if after else None,
            }
        )
    return changes


class LegalChangeRadarService:
    def __init__(self, session: AsyncSession, consultant: ConsultantPlusProviderLike):
        self.session = session
        self.consultant = consultant

    async def list_runs(
        self, *, owner_id: str, company_id: str
    ) -> list[LegalChangeRadarRunResponse]:
        runs = list(
            await self.session.scalars(
                select(LegalChangeRadarRunRecord)
                .where(
                    LegalChangeRadarRunRecord.owner_id == owner_id,
                    LegalChangeRadarRunRecord.company_id == company_id,
                )
                .order_by(LegalChangeRadarRunRecord.created_at.desc())
                .limit(50)
            )
        )
        return [await self._response(run) for run in runs]

    async def create(
        self,
        payload: LegalChangeRadarCreate,
        *,
        owner_id: str,
        company_id: str,
        idempotency_key: str,
    ) -> LegalChangeRadarRunResponse:
        digest = _request_hash(payload)
        existing = await self.session.scalar(
            select(LegalChangeRadarRunRecord).where(
                LegalChangeRadarRunRecord.company_id == company_id,
                LegalChangeRadarRunRecord.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if existing.request_hash != digest:
                raise IdempotencyConflictError(idempotency_key)
            return await self._response(existing)

        baseline = await self._source(payload.baseline_source_id, owner_id, company_id)
        current = await self._source(payload.current_source_id, owner_id, company_id)
        self._validate_sources(payload, baseline, current)

        health = self.consultant.healthcheck()
        if health.status != "ok":
            raise HTTPException(503, "Consultant+ source gate is unavailable")
        try:
            licensed = self.consultant.search(
                query=payload.subject,
                jurisdiction=payload.jurisdiction,
                effective_on=payload.effective_on,
                limit=5,
            )
        except ConsultantPlusUnavailableError as error:
            raise HTTPException(503, str(error)) from None
        except LicenseScopeExceededError as error:
            raise HTTPException(403, str(error)) from None
        if not licensed:
            raise HTTPException(424, "Consultant+ returned no applicable source metadata")

        baseline_chunks = list(
            await self.session.scalars(
                select(KnowledgeChunkRecord)
                .where(
                    KnowledgeChunkRecord.source_id == baseline.id,
                )
                .order_by(KnowledgeChunkRecord.ordinal)
            )
        )
        current_chunks = list(
            await self.session.scalars(
                select(KnowledgeChunkRecord)
                .where(
                    KnowledgeChunkRecord.source_id == current.id,
                )
                .order_by(KnowledgeChunkRecord.ordinal)
            )
        )
        if not baseline_chunks or not current_chunks:
            raise HTTPException(422, "Both sources must contain indexed chunks")
        changes = compare_chunks(baseline, current, baseline_chunks, current_chunks)
        counts = {
            kind: sum(item["change_type"] == kind for item in changes)
            for kind in ("added", "removed", "modified")
        }
        counts["high_attention"] = sum(
            item["impact_signal"] == "high_attention" for item in changes
        )
        result = LegalChangeRadarResult(
            status="awaiting_legal_review" if changes else "no_text_change",
            disclaimer=(
                "Deterministic text-diff and keyword triage only. A qualified lawyer must verify "
                "applicability, completeness and legal impact before use."
            ),
            jurisdiction=payload.jurisdiction,
            effective_on=payload.effective_on,
            baseline=self._source_card(baseline),
            current=self._source_card(current),
            changes=changes,
            counts=counts,
            consultant_plus={
                "mode": self.consultant.mode,
                "provider_status": health.status,
                "searched": True,
                "queries": [item.model_dump(mode="json") for item in licensed],
            },
            warnings=[
                "CHANGE_SIGNALS_ARE_NOT_LEGAL_CONCLUSIONS",
                "CONSULTANT_PLUS_LICENSED_TEXT_NOT_COPIED",
                "HUMAN_LEGAL_REVIEW_REQUIRED",
            ],
        )
        run = LegalChangeRadarRunRecord(
            company_id=company_id,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            request_hash=digest,
            baseline_source_id=baseline.id,
            current_source_id=current.id,
            subject=payload.subject,
            jurisdiction=payload.jurisdiction,
            effective_on=payload.effective_on,
            status=result.status,
            result=result.model_dump(mode="json"),
        )
        self.session.add(run)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            winner = await self.session.scalar(
                select(LegalChangeRadarRunRecord).where(
                    LegalChangeRadarRunRecord.company_id == company_id,
                    LegalChangeRadarRunRecord.idempotency_key == idempotency_key,
                )
            )
            if winner is None:
                raise
            if winner.request_hash != digest:
                raise IdempotencyConflictError(idempotency_key) from None
            return await self._response(winner)
        await self.session.refresh(run)
        return await self._response(run)

    async def review(
        self,
        run_id: str,
        payload: LegalChangeReviewCreate,
        *,
        reviewer_id: str,
        company_id: str,
    ) -> LegalChangeRadarRunResponse:
        run = await self.session.scalar(
            select(LegalChangeRadarRunRecord).where(
                LegalChangeRadarRunRecord.id == run_id,
                LegalChangeRadarRunRecord.company_id == company_id,
            )
        )
        if run is None:
            raise HTTPException(404, "Legal change radar run not found")
        if await self.session.scalar(
            select(LegalChangeRadarReviewRecord).where(
                LegalChangeRadarReviewRecord.run_id == run_id,
            )
        ):
            raise HTTPException(409, "Legal change radar run was already reviewed")
        review = LegalChangeRadarReviewRecord(
            run_id=run.id,
            company_id=company_id,
            reviewer_id=reviewer_id,
            decision=payload.decision,
            reason=payload.reason,
        )
        self.session.add(review)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            winner = await self.session.scalar(
                select(LegalChangeRadarReviewRecord).where(
                    LegalChangeRadarReviewRecord.run_id == run_id,
                )
            )
            if winner is not None:
                raise HTTPException(409, "Legal change radar run was already reviewed") from None
            raise
        return await self._response(run)

    async def _source(
        self, source_id: str, owner_id: str, company_id: str
    ) -> KnowledgeSourceRecord:
        source = await self.session.scalar(
            select(KnowledgeSourceRecord).where(
                KnowledgeSourceRecord.id == source_id,
                KnowledgeSourceRecord.owner_id == owner_id,
                KnowledgeSourceRecord.company_id == company_id,
                KnowledgeSourceRecord.classification.in_(("PUBLIC", "INTERNAL")),
            )
        )
        if source is None:
            raise HTTPException(404, "Knowledge source not found")
        return source

    @staticmethod
    def _validate_sources(
        payload: LegalChangeRadarCreate,
        baseline: KnowledgeSourceRecord,
        current: KnowledgeSourceRecord,
    ) -> None:
        if baseline.status not in {"ACTIVE", "SUPERSEDED", "EXPIRED"}:
            raise HTTPException(422, "Baseline source is not an approved historical version")
        if current.status != "ACTIVE":
            raise HTTPException(422, "Current source must be ACTIVE")
        if (
            baseline.jurisdiction != current.jurisdiction
            or current.jurisdiction != payload.jurisdiction
        ):
            raise HTTPException(422, "Sources and request must use the same jurisdiction")
        if baseline.effective_from >= current.effective_from:
            raise HTTPException(422, "Current source must be newer than baseline")
        if current.effective_from > payload.effective_on or (
            current.effective_to and current.effective_to < payload.effective_on
        ):
            raise HTTPException(422, "Current source is not effective on the requested date")

    @staticmethod
    def _source_card(source: KnowledgeSourceRecord) -> dict[str, object]:
        return {
            "source_id": source.id,
            "title": source.title,
            "version": source.version,
            "authority": source.authority,
            "effective_from": source.effective_from.isoformat(),
            "effective_to": source.effective_to.isoformat() if source.effective_to else None,
            "sha256": source.sha256,
        }

    async def _response(self, run: LegalChangeRadarRunRecord) -> LegalChangeRadarRunResponse:
        review = await self.session.scalar(
            select(LegalChangeRadarReviewRecord).where(
                LegalChangeRadarReviewRecord.run_id == run.id,
            )
        )
        return LegalChangeRadarRunResponse(
            id=run.id,
            baseline_source_id=run.baseline_source_id,
            current_source_id=run.current_source_id,
            subject=run.subject,
            jurisdiction=run.jurisdiction,
            effective_on=run.effective_on,
            status=run.status,
            result=LegalChangeRadarResult.model_validate(run.result),
            created_at=run.created_at,
            review=LegalChangeReviewResponse.model_validate(review) if review else None,
        )
