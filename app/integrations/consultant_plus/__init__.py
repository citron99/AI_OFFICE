"""ConsultantPlusProvider boundary: TZ V2.1 sections 4.4, 8.1, 9.3, appendix D.

Access only through the licensed channel; scraping or extending the license
scope is forbidden. Search results carry metadata (query_id, source_id,
edition, effective dates, locator) — never a forbidden full-text copy.
"""

from app.integrations.consultant_plus.exceptions import (
    ConsultantPlusUnavailableError,
    LicenseScopeExceededError,
)
from app.integrations.consultant_plus.models import (
    ConsultantPlusDocument,
    ConsultantPlusSearchResult,
    ConsultantPlusTrail,
    LicenseScope,
    ProviderMode,
)
from app.integrations.consultant_plus.provider import ConsultantPlusProvider

__all__ = [
    "ConsultantPlusDocument",
    "ConsultantPlusProvider",
    "ConsultantPlusSearchResult",
    "ConsultantPlusTrail",
    "ConsultantPlusUnavailableError",
    "LicenseScope",
    "LicenseScopeExceededError",
    "ProviderMode",
]
