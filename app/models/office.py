from typing import Literal

from pydantic import Field, field_validator

from app.models.accounting import AccountingResult
from app.models.agent import AgentResult
from app.models.enums import PolicyDecision
from app.models.legal import LegalResult


class SecurityResult(AgentResult):
    mode: Literal["security_rules_v1"] = "security_rules_v1"
    detections: dict[str, int] = Field(default_factory=dict)
    control_flags: list[str] = Field(default_factory=list)
    external_transmission_allowed: bool = False


class OfficeResult(AgentResult):
    mode: Literal["office_mock_v1"] = "office_mock_v1"
    accounting: AccountingResult | None = None
    legal: LegalResult | None = None
    security: SecurityResult
    policy_decision: PolicyDecision
    policy_version: str = "tz-v2.1-policy-v1"
    policy_reasons: list[str] = Field(default_factory=list)
    approval_id: str | None = None
    draft_id: str | None = None

    @field_validator("policy_decision", mode="before")
    @classmethod
    def _migrate_legacy_decision(cls, value: object) -> object:
        # Rows written before TZ V2.1 used the coarse three-value matrix.
        if value == "allow":
            return PolicyDecision.ALLOW_READ
        if value == "require_approval":
            return PolicyDecision.REQUIRE_OWNER_APPROVAL
        return value
