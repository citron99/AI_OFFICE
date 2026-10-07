from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.core.exceptions import GrantDeniedError
from app.models.enums import AgentType, GrantScope, RiskLevel


class Citation(BaseModel):
    source_id: str
    title: str
    locator: str | None = None
    version: str | None = None
    jurisdiction: str | None = None


class Finding(BaseModel):
    code: str
    title: str
    description: str
    risk_level: RiskLevel
    # Structured policy signal (TZ 7.2): the Policy Gate reads this flag
    # instead of hardcoding domain finding codes.
    blocks_draft: bool = False
    citations: list[Citation] = Field(default_factory=list)


class AgentContext(BaseModel):
    task_id: str
    step_id: str
    user_id: str
    input_text: str
    artifact_ids: list[str] = Field(default_factory=list)
    jurisdiction: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW


class AgentGrant(BaseModel):
    """Short-lived, least-privilege permission issued for one planned step."""

    data_scope: GrantScope
    actions: tuple[str, ...] = ()
    expires_at: datetime

    def expired(self, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        expiry = (
            self.expires_at.replace(tzinfo=UTC)
            if self.expires_at.tzinfo is None
            else self.expires_at
        )
        return expiry <= moment


def require_grant(grants: Sequence[AgentGrant], scope: GrantScope, *, now: datetime) -> AgentGrant:
    grant = next((g for g in grants if g.data_scope == scope), None)
    if grant is None:
        raise GrantDeniedError(scope.value, "not_granted")
    if grant.expired(now):
        raise GrantDeniedError(scope.value, "expired")
    return grant


class AgentResult(BaseModel):
    agent: AgentType
    status: str
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    requires_approval: bool = False
