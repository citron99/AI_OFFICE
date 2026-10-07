"""Validation and read-model projection for persisted task dependency graphs."""

from collections.abc import Iterable

from app.db.tables.tasks import TaskStepRecord
from app.models.process import ProcessDefinition, ProcessGraph, ProcessGraphNode
from app.orchestrator.contracts import ProcessDefinitionV2
from app.orchestrator.passport import ProcessDefinitionV3
from app.orchestrator.validation import _validate_dependencies

TERMINAL_FAILURE_STATES = {"failed", "cancelled"}


def build_process_graph(
    *,
    task_id: str,
    process: ProcessDefinition | ProcessDefinitionV2 | ProcessDefinitionV3 | None,
    steps: Iterable[TaskStepRecord],
    review_eligible: bool,
    reviewed: bool,
) -> ProcessGraph:
    """Project persisted steps plus the human review gate into stable node states."""

    materialized = list(steps)
    dependencies = {step.id: list(step.depends_on) for step in materialized}
    _validate_dependencies(dependencies)
    step_states = {step.id: step.state for step in materialized}
    nodes = [
        ProcessGraphNode(
            id=step.id,
            node_id=step.node_id,
            kind="agent_step",
            agent=step.agent_type,
            action=step.action,
            state=step.state,
            depends_on=list(step.depends_on),
            **_node_status(step.state, step.depends_on, step_states),
        )
        for step in materialized
    ]
    if process is not None:
        review_dependencies = [step.id for step in materialized]
        review_state = "completed" if reviewed else "queued"
        review_readiness = "completed" if reviewed else "ready" if review_eligible else "blocked"
        nodes.append(
            ProcessGraphNode(
                id="result_review",
                kind="result_review",
                state=review_state,
                readiness=review_readiness,
                depends_on=review_dependencies,
                blocked_by=[] if review_eligible or reviewed else review_dependencies,
            )
        )
    return ProcessGraph(
        task_id=task_id,
        process_id=process.id if process else None,
        process_version=process.version if process else None,
        nodes=nodes,
    )


def _node_status(
    state: str,
    dependencies: list[str],
    step_states: dict[str, str],
) -> dict[str, str | list[str]]:
    if state == "completed":
        return {"readiness": "completed", "blocked_by": []}
    if state in TERMINAL_FAILURE_STATES:
        return {"readiness": state, "blocked_by": []}
    if state == "running":
        return {"readiness": "running", "blocked_by": []}
    blocked_by = [
        dependency for dependency in dependencies if step_states[dependency] != "completed"
    ]
    return {
        "readiness": "ready" if not blocked_by else "blocked",
        "blocked_by": blocked_by,
    }
