"""Graph validation: dependencies, cycles and compatibility (TZ 3.4)."""

from collections.abc import Iterable

from app.models.task import TaskStepPlan


def validate_step_graph(plans: Iterable[TaskStepPlan]) -> None:
    """Reject duplicate, dangling, and cyclic dependencies before persistence."""

    materialized = list(plans)
    dependencies = {plan.step_id: list(plan.depends_on) for plan in materialized}
    if len(dependencies) != len(materialized):
        raise ValueError("Task graph contains duplicate step IDs")
    _validate_dependencies(dependencies)


def _validate_dependencies(dependencies: dict[str, list[str]]) -> None:
    for node_id, depends_on in dependencies.items():
        unknown = set(depends_on) - dependencies.keys()
        if unknown:
            raise ValueError(f"Task graph has unknown dependency for {node_id}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("Task graph contains a dependency cycle")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in dependencies[node_id]:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in dependencies:
        visit(node_id)
