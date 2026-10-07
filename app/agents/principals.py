"""Machine identities: an agent acts as its own principal, never as the user.

The registry is code, not a table, so identities cannot be edited at runtime.
Grants are issued per planned step from a static least-privilege matrix, carry
company/task/step scope and a short TTL, and are persisted to the
``capability_grants`` ledger before the agent touches the data.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict

from app.models.enums import AgentType, GrantScope

GRANT_TTL = timedelta(minutes=15)


class AgentPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True)

    principal_id: str
    agent_type: AgentType
    display_name: str
    description: str


PRINCIPALS: dict[AgentType, AgentPrincipal] = {
    agent: AgentPrincipal(
        principal_id=f"agt_{agent.value}",
        agent_type=agent,
        display_name=display_name,
        description=description,
    )
    for agent, display_name, description in [
        (
            AgentType.ORCHESTRATOR,
            "Оркестратор",
            "Маршрутизация запросов и сводный отчёт контура.",
        ),
        (
            AgentType.ACCOUNTANT,
            "AI-Бухгалтер",
            "Детерминированные расчёты и проверки по данным AccountingProvider.",
        ),
        (
            AgentType.LAWYER,
            "AI-Юрист",
            "Обязательный поиск в Консультант+ и вспомогательный Legal RAG.",
        ),
        (
            AgentType.SECURITY,
            "AI-Безопасник",
            "Preflight/postflight недоверенного контента и Policy Gate.",
        ),
    ]
}

GRANT_MATRIX: dict[AgentType, dict[GrantScope, tuple[str, ...]]] = {
    AgentType.ORCHESTRATOR: {GrantScope.TASK_TEXT: ("compose_report",)},
    AgentType.ACCOUNTANT: {
        GrantScope.ACCOUNTING: ("read_snapshot", "calculate_reports", "get_counterparty_status")
    },
    AgentType.SECURITY: {
        GrantScope.TASK_TEXT: ("scan_untrusted", "validate_result"),
        GrantScope.ATTACHMENTS: ("scan_untrusted",),
    },
    AgentType.LAWYER: {
        GrantScope.TASK_TEXT: ("analyze_request",),
        GrantScope.ATTACHMENTS: ("analyze_documents",),
        GrantScope.KNOWLEDGE: (
            "consultant_plus_search",
            "retrieve_law",
        ),
    },
}


def principal_for(agent: AgentType) -> AgentPrincipal:
    return PRINCIPALS[agent]


def scopes_for(agent: AgentType) -> tuple[GrantScope, ...]:
    return tuple(GRANT_MATRIX[agent])


def issue_capability_grants(
    node_id: str,
    *,
    issued_at: datetime,
    ttl: timedelta = GRANT_TTL,
) -> list[tuple[GrantScope, tuple[str, ...], datetime]]:
    """Grants for exactly the scopes the node's capability declares.

    Returns (scope, actions, expires_at) triples; the caller persists them to
    the capability_grants ledger with company/task/step/policy context.
    """

    from app.orchestrator.capabilities import CAPABILITY_INDEX

    capability = CAPABILITY_INDEX.get(node_id)
    if capability is None:
        return []
    matrix = GRANT_MATRIX[capability.agent]
    expires_at = issued_at + ttl
    return [
        (scope, matrix[scope], expires_at) for scope in capability.data_scopes if scope in matrix
    ]


def machine_identity_for(agent: AgentType) -> str:
    return PRINCIPALS[agent].principal_id
