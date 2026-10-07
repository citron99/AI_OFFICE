import asyncio

from app.agents.dummy import DummyAgent
from app.models.agent import AgentContext


def test_dummy_agent_returns_structured_result() -> None:
    result = asyncio.run(
        DummyAgent().execute(
            AgentContext(
                task_id="task_test",
                step_id="step_test",
                user_id="usr_test",
                input_text="Проверь договор",
            )
        )
    )
    assert result.status == "unsupported"
    assert result.agent.value == "orchestrator"
    assert "Проверь договор" not in result.summary
