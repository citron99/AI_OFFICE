from app.core.ids import new_id
from app.models.enums import AgentType
from app.models.task import RoutingDecision, TaskStepPlan


class SimplePlanner:
    def build(self, routing: RoutingDecision) -> list[TaskStepPlan]:
        return [
            TaskStepPlan(
                step_id=new_id("step"),
                agent=AgentType.ORCHESTRATOR,
                action="dummy_vertical_slice",
                risk_level=routing.risk_level,
                expected_output_schema="AgentResult",
            )
        ]
