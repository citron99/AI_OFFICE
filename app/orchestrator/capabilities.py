"""Capability catalog: node action × executor × least-privilege data scopes.

Adapted from the 14df04c contour work to the unified graph actions. The
registry is code: planners read it instead of hand-built branches, and the
grant matrix in ``app.agents.principals`` stays the single source of which
agent may touch which data scope.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.enums import AgentType, GrantScope

CostClass = Literal["deterministic", "llm"]


class Capability(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability_id: str
    node_id: str
    agent: AgentType
    action: str
    output_schema: str
    data_scopes: tuple[GrantScope, ...]
    cost_class: CostClass


ACCOUNTING_SNAPSHOT = Capability(
    capability_id="accounting_snapshot",
    node_id="accounting_snapshot",
    agent=AgentType.ACCOUNTANT,
    action="accountant_pilot",
    output_schema="AccountingResult",
    data_scopes=(GrantScope.ACCOUNTING,),
    cost_class="deterministic",
)

CASH_CONTROL = Capability(
    capability_id="cash_control",
    node_id="cash_control",
    agent=AgentType.ACCOUNTANT,
    action="cash_control",
    output_schema="AccountingResult",
    data_scopes=(GrantScope.ACCOUNTING,),
    cost_class="deterministic",
)

RECEIVABLE_RISK = Capability(
    capability_id="receivable_risk",
    node_id="receivable_risk",
    agent=AgentType.ACCOUNTANT,
    action="receivable_risk",
    output_schema="AccountingResult",
    data_scopes=(GrantScope.ACCOUNTING,),
    cost_class="deterministic",
)

SECURITY_PREFLIGHT = Capability(
    capability_id="security_preflight",
    node_id="security_preflight",
    agent=AgentType.SECURITY,
    action="security_preflight",
    output_schema="SecurityResult",
    data_scopes=(GrantScope.TASK_TEXT, GrantScope.ATTACHMENTS),
    cost_class="deterministic",
)

SECURITY_POSTFLIGHT = Capability(
    capability_id="security_postflight",
    node_id="security_postflight",
    agent=AgentType.SECURITY,
    action="security_postflight",
    output_schema="SecurityResult",
    # Postflight reads only structured results of other nodes, never raw data.
    data_scopes=(GrantScope.TASK_TEXT,),
    cost_class="deterministic",
)

LEGAL_REVIEW = Capability(
    capability_id="legal_review",
    node_id="legal_review",
    agent=AgentType.LAWYER,
    action="lawyer_pilot",
    output_schema="LegalResult",
    data_scopes=(GrantScope.TASK_TEXT, GrantScope.ATTACHMENTS, GrantScope.KNOWLEDGE),
    cost_class="llm",
)

CAPABILITY_INDEX: dict[str, Capability] = {
    capability.node_id: capability
    for capability in (
        ACCOUNTING_SNAPSHOT,
        CASH_CONTROL,
        RECEIVABLE_RISK,
        SECURITY_PREFLIGHT,
        SECURITY_POSTFLIGHT,
        LEGAL_REVIEW,
    )
}


def capability_for_node(node_id: str | None) -> Capability | None:
    if node_id is None:
        return None
    return CAPABILITY_INDEX.get(node_id)
