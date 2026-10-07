from app.models.enums import AgentType, RiskLevel, TaskCategory
from app.models.task import RoutingDecision


class KeywordRouter:
    _accounting = {"счёт", "счет", "платёж", "платеж", "расход", "доход", "invoice"}
    _legal = {"договор", "право", "юрист", "nda", "contract"}
    _security = {"безопас", "секрет", "персональ", "утеч", "security", "конфиденц", "чувствит"}

    def classify(self, text: str, requested_agent: AgentType | None = None) -> RoutingDecision:
        if requested_agent and requested_agent is not AgentType.ORCHESTRATOR:
            category = {
                AgentType.ACCOUNTANT: TaskCategory.ACCOUNTING,
                AgentType.LAWYER: TaskCategory.LEGAL,
                AgentType.SECURITY: TaskCategory.SECURITY,
            }[requested_agent]
            return RoutingDecision(
                category=category,
                confidence=1.0,
                required_agents=[requested_agent],
                risk_level=RiskLevel.MEDIUM,
                reason_code="USER_SELECTED_AGENT",
            )

        normalized = text.casefold()
        matches: list[tuple[TaskCategory, AgentType]] = []
        if any(word in normalized for word in self._accounting):
            matches.append((TaskCategory.ACCOUNTING, AgentType.ACCOUNTANT))
        if any(word in normalized for word in self._legal):
            matches.append((TaskCategory.LEGAL, AgentType.LAWYER))
        if any(word in normalized for word in self._security):
            matches.append((TaskCategory.SECURITY, AgentType.SECURITY))

        if len(matches) > 1:
            return RoutingDecision(
                category=TaskCategory.MIXED,
                confidence=0.9,
                required_agents=[agent for _, agent in matches],
                risk_level=RiskLevel.HIGH,
                reason_code="MULTIPLE_DOMAINS",
            )
        if len(matches) == 1:
            category, agent = matches[0]
            return RoutingDecision(
                category=category,
                confidence=0.85,
                required_agents=[agent],
                risk_level=RiskLevel.MEDIUM,
                reason_code="KEYWORD_MATCH",
            )
        return RoutingDecision(
            category=TaskCategory.UNSUPPORTED,
            confidence=0.4,
            required_agents=[AgentType.ORCHESTRATOR],
            risk_level=RiskLevel.LOW,
            reason_code="NO_DOMAIN_MATCH",
        )
