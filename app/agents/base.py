from abc import ABC, abstractmethod

from app.models.agent import AgentContext, AgentResult
from app.models.enums import AgentType


class BaseAgent(ABC):
    @property
    @abstractmethod
    def agent_type(self) -> AgentType:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult:
        raise NotImplementedError
