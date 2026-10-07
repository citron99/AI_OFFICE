from app.models.enums import AgentType, RiskLevel, TaskCategory
from app.orchestrator.router import KeywordRouter


def test_router_detects_mixed_supplier_review() -> None:
    decision = KeywordRouter().classify("Проверь договор и счёт нового подрядчика на безопасность")
    assert decision.category is TaskCategory.MIXED
    assert decision.risk_level is RiskLevel.HIGH
    assert decision.required_agents == [
        AgentType.ACCOUNTANT,
        AgentType.LAWYER,
        AgentType.SECURITY,
    ]


def test_requested_agent_overrides_keyword_route() -> None:
    decision = KeywordRouter().classify("Общий вопрос", AgentType.LAWYER)
    assert decision.category is TaskCategory.LEGAL
    assert decision.required_agents == [AgentType.LAWYER]
