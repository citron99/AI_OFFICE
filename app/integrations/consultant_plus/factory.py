from datetime import date

from app.config import Settings
from app.integrations.consultant_plus.exceptions import ConsultantPlusUnavailableError
from app.integrations.consultant_plus.licensed_adapter import LicensedConsultantPlusAdapter
from app.integrations.consultant_plus.mock import MockConsultantPlusProvider
from app.integrations.consultant_plus.models import (
    ConsultantPlusDocument,
    ConsultantPlusSearchResult,
    LicenseScope,
    ProviderHealth,
    ProviderMode,
)


class UnavailableConsultantPlusProvider:
    """Mode "off": every legal route stops in WAITING_SOURCE, never answers from memory."""

    mode = "off"

    def search(
        self,
        *,
        query: str,
        jurisdiction: str,
        effective_on: date,
        limit: int = 5,
    ) -> list[ConsultantPlusSearchResult]:
        del query, jurisdiction, effective_on, limit
        raise ConsultantPlusUnavailableError("Consultant+ integration is switched off")

    def get_document(self, document_id: str, *, edition: str) -> ConsultantPlusDocument:
        del document_id, edition
        raise ConsultantPlusUnavailableError("Consultant+ integration is switched off")

    def get_citation(self, locator: str) -> ConsultantPlusSearchResult:
        del locator
        raise ConsultantPlusUnavailableError("Consultant+ integration is switched off")

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(status="unavailable", detail="Consultant+ integration is off")

    def license_scope(self) -> LicenseScope | None:
        return None


ConsultantPlusProviderLike = (
    MockConsultantPlusProvider | LicensedConsultantPlusAdapter | UnavailableConsultantPlusProvider
)


def create_consultant_plus_provider(settings: Settings) -> ConsultantPlusProviderLike:
    mode: ProviderMode = settings.consultant_plus_mode
    if mode == "mock":
        return MockConsultantPlusProvider()
    if mode == "licensed":
        return LicensedConsultantPlusAdapter()
    return UnavailableConsultantPlusProvider()
