from dataclasses import dataclass
from time import perf_counter

from app.agents.base import BaseAgent
from app.models.agent import AgentContext, AgentResult
from app.models.enums import AgentType
from app.models.task import RoutingDecision, TaskStepPlan
from app.orchestrator.planner import SimplePlanner
from app.orchestrator.router import KeywordRouter


@dataclass(slots=True)
class OrchestrationResult:
    routing: RoutingDecision
    plan: list[TaskStepPlan]
    result: AgentResult
    latency_ms: int


class Orchestrator:
    def __init__(
        self,
        *,
        router: KeywordRouter,
        planner: SimplePlanner,
        dummy_agent: BaseAgent,
    ) -> None:
        self.router = router
        self.planner = planner
        self.dummy_agent = dummy_agent

    async def prepare(
        self,
        *,
        text: str,
        requested_agent: AgentType | None,
    ) -> tuple[RoutingDecision, list[TaskStepPlan]]:
        routing = self.router.classify(text, requested_agent)
        return routing, self.planner.build(routing)

    async def execute(
        self,
        *,
        task_id: str,
        step: TaskStepPlan,
        user_id: str,
        text: str,
        artifact_ids: list[str],
    ) -> tuple[AgentResult, int]:
        started = perf_counter()
        result = await self.dummy_agent.execute(
            AgentContext(
                task_id=task_id,
                step_id=step.step_id,
                user_id=user_id,
                input_text=text,
                artifact_ids=artifact_ids,
                risk_level=step.risk_level,
            )
        )
        return result, round((perf_counter() - started) * 1000)
