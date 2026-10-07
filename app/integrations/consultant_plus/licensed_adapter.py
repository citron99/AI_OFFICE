"""Production skeleton for the licensed Consultant+ adapter.

Deployment requires the customer-confirmed licensed channel (TZ 15.2): scope,
integration owner and permitted export. Until configured, every legal route
stops in WAITING_SOURCE instead of falling back to model memory.
"""

from datetime import date

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


class LicensedConsultantPlusAdapter:
    """Fill in with the approved commercial integration; read-only by contract."""

    mode = "licensed"

    def __init__(self, *, scope: LicenseScope | None = None) -> None:
        self._scope = scope

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(status="unavailable", detail="Licensed adapter is not configured")

    def license_scope(self) -> LicenseScope:
        if self._scope is None:
            raise LicenseScopeExceededError("No approved license scope configured")
        return self._scope

    def search(
        self,
        *,
        query: str,
        jurisdiction: str,
        effective_on: date,
        limit: int = 5,
    ) -> list[ConsultantPlusSearchResult]:
        del query, jurisdiction, effective_on, limit
        raise ConsultantPlusUnavailableError("Licensed adapter is not configured")

    def get_document(self, document_id: str, *, edition: str) -> ConsultantPlusDocument:
        del document_id, edition
        raise ConsultantPlusUnavailableError("Licensed adapter is not configured")

    def get_citation(self, locator: str) -> ConsultantPlusSearchResult:
        del locator
        raise ConsultantPlusUnavailableError("Licensed adapter is not configured")
