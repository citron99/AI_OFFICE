"""Evidence retrieval with an explicitly enabled, citation-checked analysis stage.

Every legal route starts with the mandatory Consultant+ search (TZ 4.4, LEG-001).
The local Legal RAG is auxiliary and runs only after the licensed search; if the
licensed channel is unavailable the route stops in WAITING_SOURCE and no final
legal conclusion is produced from model memory.
"""

import asyncio
from datetime import date

from app.integrations.consultant_plus.exceptions import (
    ConsultantPlusUnavailableError,
    LicenseScopeExceededError,
)
from app.integrations.consultant_plus.factory import ConsultantPlusProviderLike
from app.integrations.consultant_plus.models import ConsultantPlusTrail, ProviderMode
from app.llm.base import LLMProvider
from app.models.agent import Citation
from app.models.enums import AgentType
from app.models.knowledge import SearchRequest
from app.models.legal import LegalResult
from app.services.knowledge import KnowledgeService
from app.services.legal_analysis import analyze, extract_attachments


class LawyerAgent:
    def __init__(
        self,
        knowledge: KnowledgeService,
        provider: LLMProvider | None = None,
        consultant: ConsultantPlusProviderLike | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.provider = provider
        self.consultant = consultant

    async def execute(
        self,
        *,
        text: str,
        user_id: str,
        company_id: str,
        jurisdiction: str | None,
        effective_on: date | None,
        artifact_ids: list[str],
    ) -> LegalResult:
        result = LegalResult(
            agent=AgentType.LAWYER,
            status="waiting_input",
            summary="Требуется контекст проверки.",
            jurisdiction=jurisdiction,
            effective_on=effective_on,
            retrieval_version=self.knowledge.retrieval_version,
            warnings=["Пилотный режим: не окончательное юридическое заключение."],
        )
        if jurisdiction is None:
            result.unresolved_questions.append(
                "JURISDICTION_REQUIRED: укажите код страны (например LV)."
            )
        if effective_on is None:
            result.unresolved_questions.append("EFFECTIVE_DATE_REQUIRED: укажите дату проверки.")
        if result.unresolved_questions:
            return result
        assert jurisdiction is not None and effective_on is not None

        # --- Mandatory licensed search step (LEG-001) ----------------------
        if self.consultant is None:
            result.status = "waiting_source"
            result.summary = (
                "WAITING_SOURCE: Консультант+ не настроен; правовой вывод не формируется."
            )
            result.consultant_plus = ConsultantPlusTrail(
                mode="off", provider_status="unavailable", searched=False
            )
            return result
        scope = self.consultant.license_scope()
        try:
            searches = self.consultant.search(
                query=text, jurisdiction=jurisdiction, effective_on=effective_on
            )
        except ConsultantPlusUnavailableError:
            result.status = "waiting_source"
            result.summary = (
                "WAITING_SOURCE: Консультант+ недоступен; окончательный вывод запрещён."
            )
            result.consultant_plus = ConsultantPlusTrail(
                mode=cast_mode(self.consultant.mode),
                provider_status="unavailable",
                license_scope=scope,
                searched=False,
            )
            return result
        except LicenseScopeExceededError as error:
            # TZ LEG-005: another jurisdiction still needs its approved official
            # source; without one the route stops in WAITING_SOURCE.
            official = getattr(self.consultant, "official_source_for", lambda _j: None)(
                jurisdiction
            )
            if official is None:
                result.status = "waiting_source"
                result.summary = (
                    "WAITING_SOURCE: запрос выходит за рамки лицензии Консультант+, "
                    "утверждённый официальный источник юрисдикции не задан."
                )
                result.warnings.append(str(error))
                result.consultant_plus = ConsultantPlusTrail(
                    mode=cast_mode(self.consultant.mode),
                    provider_status="unavailable",
                    license_scope=scope,
                    searched=False,
                )
                return result
            result.warnings.append(
                f"FOREIGN_JURISDICTION_SOURCE: подтверждено официальным источником "
                f"{official.source_id} ({official.authority})."
            )
            searches = [official.to_provider_result(queried=text)]
        result.consultant_plus = ConsultantPlusTrail(
            mode=cast_mode(self.consultant.mode),
            provider_status="ok",
            license_scope=scope,
            searched=True,
            queries=searches,
        )

        # Edition/effective-date validation on the task date (LEG-003).
        effective_sources = [
            item
            for item in searches
            if item.effective_from <= effective_on
            and (item.effective_to is None or effective_on <= item.effective_to)
        ]
        if not effective_sources:
            result.status = "legal_source_not_found"
            result.summary = (
                "LEGAL_SOURCE_NOT_FOUND: в Консультант+ нет актуального подтверждающего "
                "материала; выводы не сделаны."
            )
            result.recommended_actions = [
                "Проверьте наличие действующих источников нужной юрисдикции в Консультант+."
            ]
            return result

        result.documents = await extract_attachments(
            self.knowledge,
            artifact_ids,
            user_id,
            company_id,
        )
        # Prepare all windows before searching: overflow fails the whole request,
        # rather than silently reviewing only the first part of a document.
        queries = await asyncio.to_thread(
            self.knowledge.prepare_queries,
            [text, *(part.text for part in result.documents)],
        )
        response = await self.knowledge.search(
            SearchRequest(
                query=queries[0],
                jurisdiction=jurisdiction,
                effective_on=effective_on,
                top_k=self.knowledge.settings.legal_rag_top_k,
            ),
            owner_id=user_id,
            company_id=company_id,
        )
        hits = {hit.chunk_id: hit for hit in response.hits}
        for query in queries[1:]:
            additional = await self.knowledge.search(
                SearchRequest(
                    query=query,
                    jurisdiction=jurisdiction,
                    effective_on=effective_on,
                    top_k=self.knowledge.settings.legal_rag_top_k,
                ),
                owner_id=user_id,
                company_id=company_id,
            )
            for hit in additional.hits:
                if hit.chunk_id not in hits or hit.score > hits[hit.chunk_id].score:
                    hits[hit.chunk_id] = hit
        response.hits = sorted(hits.values(), key=lambda hit: -hit.score)[
            : self.knowledge.settings.legal_rag_top_k
        ]
        result.warnings.extend(response.warnings)
        if artifact_ids and self.provider is None:
            result.warnings.append(
                "ATTACHMENT_ANALYSIS_DISABLED: вложения разобраны и использованы в поиске, "
                "но LLM-анализ выключен."
            )
        result.evidence = response.hits
        result.legal_sources_found = bool(response.hits)
        if not response.hits:
            # The licensed channel found sources, but the auxiliary local index has
            # nothing to quote: retrieval-only summary with the Consultant+ trail.
            result.status = "retrieval_only"
            result.summary = (
                "Консультант+ вернул источники; локальный индекс не содержит цитат, "
                "их применимость должен проверить юрист."
            )
            result.citations = [
                Citation(
                    source_id=item.source_id,
                    title=item.title,
                    locator=item.locator,
                    version=item.edition,
                    jurisdiction=item.jurisdiction,
                )
                for item in effective_sources
            ]
            if artifact_ids and self.provider is None:
                result.warnings.append(
                    "ATTACHMENT_ANALYSIS_DISABLED: вложения разобраны и использованы в "
                    "поиске, но LLM-анализ выключен."
                )
            return result
        result.status = "retrieval_only"
        result.summary = "Найдены фрагменты источников. Их применимость должен проверить юрист."
        result.citations = [
            Citation(
                source_id=hit.source_id,
                title=hit.title,
                locator=hit.locator,
                version=hit.version,
                jurisdiction=hit.jurisdiction,
            )
            for hit in response.hits
        ]
        result.warnings.append("Возможные противоречия источников автоматически не разрешаются.")
        if self.provider is not None:
            settings = self.knowledge.settings
            return await analyze(
                self.provider,
                result,
                query=text,
                model_id=settings.llm_model if settings.llm_provider != "mock" else "mock",
                timeout_seconds=settings.legal_analysis_timeout_seconds,
            )
        result.warnings.append("LEGAL_ANALYSIS_DISABLED: LLM не вызывался.")
        return result


_MODES: dict[str, ProviderMode] = {"mock": "mock", "licensed": "licensed", "off": "off"}


def cast_mode(mode: str) -> ProviderMode:
    return _MODES.get(mode, "mock")
