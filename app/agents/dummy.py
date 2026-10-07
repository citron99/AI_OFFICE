from app.agents.base import BaseAgent
from app.models.agent import AgentContext, AgentResult
from app.models.enums import AgentType


class DummyAgent(BaseAgent):
    @property
    def agent_type(self) -> AgentType:
        return AgentType.ORCHESTRATOR

    async def execute(self, context: AgentContext) -> AgentResult:
        return AgentResult(
            agent=self.agent_type,
            status="unsupported",
            summary="Запрос не отнесён к поддерживаемой области; действия не выполнялись.",
            assumptions=["Поддерживаются бухгалтерия, договоры и проверка безопасности."],
            recommended_actions=["Уточните вопрос или явно выберите агента."],
        )
