import pytest

from app.db.tables.tasks import TaskStepRecord
from app.models.enums import AgentType, RiskLevel
from app.models.process import office_process
from app.models.task import TaskStepPlan
from app.orchestrator.validation import validate_step_graph
from app.services.process_graph import build_process_graph


def plan(step_id: str, depends_on: list[str] | None = None) -> TaskStepPlan:
    return TaskStepPlan(
        step_id=step_id,
        agent=AgentType.SECURITY,
        action="security_pilot",
        depends_on=depends_on or [],
        risk_level=RiskLevel.MEDIUM,
        expected_output_schema="AgentResult",
    )


def step(step_id: str, state: str, depends_on: list[str] | None = None) -> TaskStepRecord:
    return TaskStepRecord(
        id=step_id,
        task_id="task_graph",
        agent_type="security",
        action="security_pilot",
        state=state,
        depends_on=depends_on or [],
    )


def test_graph_rejects_duplicate_dangling_and_cyclic_dependencies() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_step_graph([plan("a"), plan("a")])
    with pytest.raises(ValueError, match="unknown"):
        validate_step_graph([plan("a", ["missing"])])
    with pytest.raises(ValueError, match="cycle"):
        validate_step_graph([plan("a", ["b"]), plan("b", ["a"])])


def test_graph_exposes_readiness_and_human_review_gate() -> None:
    graph = build_process_graph(
        task_id="task_graph",
        process=office_process("usr_demo_owner"),
        steps=[step("collect", "completed"), step("security", "completed", ["collect"])],
        review_eligible=True,
        reviewed=False,
    )
    nodes = {node.id: node for node in graph.nodes}
    assert nodes["collect"].readiness == "completed"
    assert nodes["security"].readiness == "completed"
    assert nodes["result_review"].readiness == "ready"
    assert nodes["result_review"].depends_on == ["collect", "security"]


def test_graph_blocks_dependant_nodes_after_failure() -> None:
    graph = build_process_graph(
        task_id="task_graph",
        process=None,
        steps=[step("collect", "failed"), step("security", "queued", ["collect"])],
        review_eligible=False,
        reviewed=False,
    )
    nodes = {node.id: node for node in graph.nodes}
    assert nodes["collect"].readiness == "failed"
    assert nodes["security"].readiness == "blocked"
    assert nodes["security"].blocked_by == ["collect"]
