"""Deterministic mock of the licensed Consultant+ channel.

The mock keeps a small synthetic corpus with editions and effective dates so
the mandatory-search flow, edition checks and controlled stops can be tested
without the licensed system. It never stands in for a real license.
"""

import re
from datetime import UTC, date, datetime
from hashlib import sha256

from app.integrations.consultant_plus.exceptions import (
    ConsultantPlusUnavailableError,
    LicenseScopeExceededError,
)
from app.integrations.consultant_plus.models import (
    ConsultantPlusDocument,
    ConsultantPlusSearchResult,
    LicenseScope,
    ProviderHealth,
)

_SYNTHETIC_DOCS: tuple[ConsultantPlusDocument, ...] = (
    ConsultantPlusDocument(
        query_id="seed_document",
        source_id="kplus-lv-0001",
        title="Komercdarbības līgumu apmaksa un samaksas termiņš",
        jurisdiction="LV",
        document_type="law",
        edition="red. 2024-01-01",
        effective_from=date(2024, 1, 1),
        effective_to=None,
        locator="KL 1.1",
        authority="Synthetic Registrator",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        text=(
            "Pants 1.1. Maksājums ir jāveic līgumā noteiktajā termiņā pēc piegādes "
            "un pieņemšanas aktparakstīšanas. Šis ir sintētisks dokuments, nevis tiesību akts."
        ),
    ),
    ConsultantPlusDocument(
        query_id="seed_document",
        source_id="kplus-lv-0002",
        title="Līgumsodu (kavējuma naudas) piemērošana",
        jurisdiction="LV",
        document_type="law",
        edition="red. 2023-06-01",
        effective_from=date(2023, 6, 1),
        effective_to=date(2025, 12, 31),
        locator="KL 1.2",
        authority="Synthetic Registrator",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        text=(
            "Pants 1.2. Līgumsoda apmērs un aprēķins tiek piemērots saskaņā ar līgumu. "
            "Šis ir sintētisks dokuments, nevis tiesību akts."
        ),
    ),
    ConsultantPlusDocument(
        query_id="seed_document",
        source_id="kplus-lv-0003",
        title="Synthetic contract: payment is due after acceptance",
        jurisdiction="LV",
        document_type="law",
        edition="red. 2026-01-01",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        locator="SYN-C 1",
        authority="Synthetic Registrator",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        text=(
            "Article 1. Synthetic contract: payment is due after acceptance of "
            "delivery. Late payment triggers a contractual penalty. This fixture "
            "is not law."
        ),
    ),
    ConsultantPlusDocument(
        query_id="seed_document",
        source_id="kplus-lv-0004",
        title="Synthetic invoice, overdue payment and liability",
        jurisdiction="LV",
        document_type="law",
        edition="red. 2026-01-01",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        locator="SYN-C 2",
        authority="Synthetic Registrator",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        text=(
            "Article 2. A synthetic invoice must state the amount, tax and due "
            "date. Overdue payment accrues interest and termination liability. "
            "This fixture is not law."
        ),
    ),
    ConsultantPlusDocument(
        query_id="seed_document",
        source_id="kplus-de-0001",
        title="Synthetisches Gesetz: Zahlung und Verzug",
        jurisdiction="DE",
        document_type="law",
        edition="red. 2026-01-01",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        locator="DE-SYN 1",
        authority="Synthetic Official Source (DE)",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        text=(
            "Paragraph 1. Zahlungen sind zu dem im Vertrag bestimmten Zeitpunkt zu "
            "leisten. Synthetisches Dokument, kein Gesetzestext."
        ),
    ),
    ConsultantPlusDocument(
        query_id="seed_document",
        source_id="kplus-ru-0001",
        title="Поставка, оплата товара и последствия просрочки",
        jurisdiction="RU",
        document_type="code",
        edition="red. 2025-01-01",
        effective_from=date(2025, 1, 1),
        effective_to=None,
        locator="ГК ст. 486",
        authority="Synthetic Official Source",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        text=(
            "Статья 486. Покупатель обязан оплатить товар непосредственно до или после "
            "передачи ему продавцом товара. Синтетический документ, не нормативный акт."
        ),
    ),
    ConsultantPlusDocument(
        query_id="seed_document",
        source_id="kplus-ru-0002",
        title="Ответственность за неисполнение денежного обязательства",
        jurisdiction="RU",
        document_type="code",
        edition="red. 2024-09-01",
        effective_from=date(2024, 9, 1),
        effective_to=None,
        locator="ГК ст. 395",
        authority="Synthetic Official Source",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        text=(
            "Статья 395. За пользование чужими денежными средствами подлежат уплате "
            "проценты. Синтетический документ, не нормативный акт."
        ),
    ),
)


def _tokenize(value: str) -> set[str]:
    return {token.lower() for token in re.findall(r"\w+", value) if len(token) > 2}


class MockConsultantPlusProvider:
    """Licensed-channel stand-in with deterministic keyword search."""

    mode = "mock"

    def __init__(
        self,
        *,
        documents: tuple[ConsultantPlusDocument, ...] = _SYNTHETIC_DOCS,
        available: bool = True,
        official_sources: dict[str, ConsultantPlusDocument] | None = None,
    ) -> None:
        self._documents = documents
        self._available = available
        # TZ LEG-005: for jurisdictions outside the license scope, the route
        # may proceed only with an approved official source of that law.
        self._official_sources = official_sources or {
            "DE": next(d for d in documents if d.source_id == "kplus-de-0001"),
        }

    def official_source_for(self, jurisdiction: str) -> ConsultantPlusDocument | None:
        return self._official_sources.get(jurisdiction)

    def healthcheck(self) -> ProviderHealth:
        if not self._available:
            return ProviderHealth(status="unavailable", detail="Licensed channel is offline")
        return ProviderHealth(status="ok", detail="Synthetic licensed corpus available")

    def license_scope(self) -> LicenseScope:
        return LicenseScope(
            jurisdictions=tuple(sorted({doc.jurisdiction for doc in self._documents})),
            allowed_channels=("mock_licensed_export",),
            scope_owner="MVP synthetic integration owner",
        )

    def search(
        self,
        *,
        query: str,
        jurisdiction: str,
        effective_on: date,
        limit: int = 5,
    ) -> list[ConsultantPlusSearchResult]:
        if not self._available:
            raise ConsultantPlusUnavailableError(
                "Consultant+ is unavailable: the legal route must stop in WAITING_SOURCE"
            )
        if jurisdiction not in self.license_scope().jurisdictions:
            raise LicenseScopeExceededError(
                f"Jurisdiction {jurisdiction} is outside the approved license scope"
            )
        query_tokens = _tokenize(query)
        scored: list[tuple[int, ConsultantPlusDocument]] = []
        for document in self._documents:
            if document.jurisdiction != jurisdiction:
                continue
            if not document.effective_from <= effective_on:
                continue
            if document.effective_to is not None and effective_on > document.effective_to:
                continue
            corpus_tokens = _tokenize(f"{document.title} {document.text}")
            score = len(query_tokens & corpus_tokens)
            if score:
                scored.append((score, document))
        scored.sort(key=lambda pair: (-pair[0], pair[1].source_id))
        retrieved_at = datetime.now(UTC)
        results: list[ConsultantPlusSearchResult] = []
        for _, document in scored[:limit]:
            results.append(
                ConsultantPlusSearchResult(
                    query_id=self._query_id(query, jurisdiction, effective_on),
                    source_id=document.source_id,
                    title=document.title,
                    jurisdiction=document.jurisdiction,
                    document_type=document.document_type,
                    edition=document.edition,
                    effective_from=document.effective_from,
                    effective_to=document.effective_to,
                    locator=document.locator,
                    authority=document.authority,
                    retrieved_at=retrieved_at,
                )
            )
        return results

    def get_document(self, document_id: str, *, edition: str) -> ConsultantPlusDocument:
        for document in self._documents:
            if document.source_id == document_id and document.edition == edition:
                return document
        raise LookupError("Document not found in the licensed scope")

    def get_citation(self, locator: str) -> ConsultantPlusSearchResult:
        for document in self._documents:
            if document.locator == locator:
                return ConsultantPlusSearchResult(
                    query_id=self._query_id(locator, document.jurisdiction, date(2026, 1, 1)),
                    source_id=document.source_id,
                    title=document.title,
                    jurisdiction=document.jurisdiction,
                    document_type=document.document_type,
                    edition=document.edition,
                    effective_from=document.effective_from,
                    effective_to=document.effective_to,
                    locator=document.locator,
                    authority=document.authority,
                    retrieved_at=document.retrieved_at,
                )
        raise LookupError("Locator not found in the licensed scope")

    @staticmethod
    def _query_id(query: str, jurisdiction: str, effective_on: date) -> str:
        digest = sha256(
            f"{jurisdiction}|{effective_on.isoformat()}|{query.lower()}".encode()
        ).hexdigest()[:24]
        return f"qp_{digest}"
