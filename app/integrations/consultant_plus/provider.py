"""ConsultantPlusProvider contract (TZ V2.1 section 9.3)."""

from datetime import date
from typing import Protocol

from app.integrations.consultant_plus.models import (
    ConsultantPlusDocument,
    ConsultantPlusSearchResult,
    LicenseScope,
    ProviderHealth,
)


class ConsultantPlusProvider(Protocol):
    mode: str

    def search(
        self,
        *,
        query: str,
        jurisdiction: str,
        effective_on: date,
        limit: int = 5,
    ) -> list[ConsultantPlusSearchResult]: ...

    def get_document(self, document_id: str, *, edition: str) -> ConsultantPlusDocument: ...

    def get_citation(self, locator: str) -> ConsultantPlusSearchResult: ...

    def healthcheck(self) -> ProviderHealth: ...

    def license_scope(self) -> LicenseScope: ...
