from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

ProviderMode = Literal["mock", "licensed", "off"]


class ProviderHealth(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    detail: str | None = None


class LicenseScope(BaseModel):
    jurisdictions: tuple[str, ...]
    allowed_channels: tuple[str, ...]
    scope_owner: str
    valid_until: date | None = None


class ConsultantPlusSearchResult(BaseModel):
    """Metadata of one licensed source card found for a query."""

    query_id: str = Field(min_length=8, max_length=64)
    source_id: str = Field(min_length=1, max_length=100)
    title: str
    jurisdiction: str
    document_type: str
    edition: str
    effective_from: date
    effective_to: date | None = None
    locator: str
    authority: str
    retrieved_at: datetime


class ConsultantPlusDocument(ConsultantPlusSearchResult):
    """A licensed document available to the connector (synthetic for the mock)."""

    text: str

    def to_provider_result(self, *, queried: str) -> "ConsultantPlusSearchResult":
        """Project the document onto the search-result shape for a route trail."""
        from hashlib import sha256

        return ConsultantPlusSearchResult(
            query_id=f"qs_{sha256(queried.encode()).hexdigest()[:24]}",
            source_id=self.source_id,
            title=self.title,
            jurisdiction=self.jurisdiction,
            document_type=self.document_type,
            edition=self.edition,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            locator=self.locator,
            authority=self.authority,
            retrieved_at=self.retrieved_at,
        )


class ConsultantPlusTrail(BaseModel):
    """Evidence trail of the mandatory search step, stored with the result."""

    mode: ProviderMode
    provider_status: Literal["ok", "unavailable"]
    license_scope: LicenseScope | None = None
    searched: bool = False
    queries: list[ConsultantPlusSearchResult] = Field(default_factory=list)
