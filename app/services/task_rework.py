"""Result rework: immutable child runs for selected graph nodes and safety closure."""

from app.core.exceptions import (
    RunBudgetExceededError,
    TaskNotFoundError,
)
from app.db.tables.tasks import TaskRecord
from app.models.task import TaskCreate, TaskResponse
from app.orchestrator.contracts import ProcessDefinitionV2, RunBudget, RunUsage
from app.orchestrator.passport import ProcessDefinitionV3
from app.orchestrator.processes import process_from_snapshot
from app.services.approvals import audit
from app.services.task_core import TaskServiceCore


class TaskReworkMixin(TaskServiceCore):
    async def create_rework(
        self,
        source: TaskRecord,
        *,
        target_node_ids: list[str],
        user_id: str,
        company_id: str,
        queued: bool = False,
    ) -> TaskResponse:
        """Create a new immutable run for selected graph work and its safety closure."""

        if source.process_snapshot is None or source.run_budget_snapshot is None:
            raise RuntimeError("Result has no executable process snapshot")
        process = process_from_snapshot(source.process_snapshot)
        if not isinstance(process, (ProcessDefinitionV2, ProcessDefinitionV3)):
            raise RuntimeError("Legacy process results cannot be reworked")
        budget = RunBudget.model_validate(source.run_budget_snapshot)
        next_cycle = source.rework_cycle + 1
        if next_cycle > budget.max_rework_cycles:
            raise RunBudgetExceededError("RUN_REWORK_LIMIT_REACHED")
        source_nodes = {
            step.node_id
            for step in await self.repository.list_steps(source.id)
            if step.node_id is not None
        }
        unknown = set(target_node_ids) - source_nodes
        if unknown:
            raise ValueError("Rework target is not a node of the reviewed task")
        if source.company_id != company_id:
            raise TaskNotFoundError(source.id)
        request = TaskCreate.model_validate(source.request_data)
        child = await self.repository.create(
            user_id=user_id,
            payload=request,
            company_id=company_id,
        )
        child.process_snapshot = source.process_snapshot
        child.run_budget_snapshot = source.run_budget_snapshot
        child.run_usage = RunUsage(rework_cycles=next_cycle).model_dump(mode="json")
        child.rework_parent_task_id = source.id
        child.rework_target_node_ids = target_node_ids
        child.rework_cycle = next_cycle
        audit(
            self.session,
            source,
            "rework_started",
            {"task_id": child.id, "target_node_ids": target_node_ids, "cycle": next_cycle},
        )
        if queued:
            await self.session.commit()
            return await self._publish_for_execution(child)
        return await self._execute(
            request,
            user_id=user_id,
            company_id=company_id,
            existing_task=child,
        )


def _rework_execution_scope(
    process: ProcessDefinitionV2 | ProcessDefinitionV3,
    active_nodes: list[str],
    targets: list[str],
) -> list[str]:
    """Select requested nodes, their downstream, and required safety inputs.

    Reusing a predecessor output would make a rework depend on stale evidence.
    The closure therefore reruns only the minimal upstream control nodes needed
    to execute the selected downstream branch safely.
    """

    active = set(active_nodes)
    if not set(targets) <= active:
        raise ValueError("Rework target is not active for this task route")
    specs = {node.id: node for node in process.nodes}
    dependents = {
        node.id: {candidate.id for candidate in process.nodes if node.id in candidate.depends_on}
        for node in process.nodes
    }
    selected = set(targets)
    frontier = list(targets)
    while frontier:
        node_id = frontier.pop()
        for dependent in dependents[node_id] & active:
            if dependent not in selected:
                selected.add(dependent)
                frontier.append(dependent)
    frontier = list(selected)
    while frontier:
        node_id = frontier.pop()
        for dependency in specs[node_id].depends_on:
            if dependency in active and dependency not in selected:
                selected.add(dependency)
                frontier.append(dependency)
    return [node_id for node_id in active_nodes if node_id in selected]
