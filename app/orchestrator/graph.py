"""Dependency-driven executor for server-authored task graphs."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import ModelOutputInvalidError, NodeExecutionFailed, RetryableAgentError
from app.models.accounting import AccountingResult
from app.models.agent import AgentResult
from app.models.legal import LegalResult
from app.models.office import SecurityResult
from app.models.task import TaskStepPlan
from app.orchestrator.validation import validate_step_graph


@dataclass(frozen=True, slots=True)
class NodeExecution:
    output: AgentResult
    latency_ms: int
    attempts: int = 1


ClaimBatch = Callable[[tuple[TaskStepPlan, ...]], Awaitable[None]]
RunNode = Callable[[TaskStepPlan, Mapping[str, AgentResult]], Awaitable[NodeExecution]]
CompleteNode = Callable[[TaskStepPlan, NodeExecution], Awaitable[None]]


class GraphExecutor:
    """Run every ready DAG layer, concurrently where dependencies permit it.

    Persistence is supplied as callbacks.  This keeps the scheduler independent
    of FastAPI, Celery and SQLAlchemy while ensuring a service can atomically
    claim a layer before any agent call leaves the process.

    Each node runs under its declared timeout with bounded retry/backoff for
    errors the process author marked retryable; exhausted nodes stop the run
    with NodeExecutionFailed so the task lands in FAILED_SAFE, never silently.
    Confirmed outputs supplied as ``resume`` let a run continue from the last
    checkpoint instead of repeating completed nodes.
    """

    _output_contracts: dict[str, type[AgentResult]] = {
        "AgentResult": AgentResult,
        "AccountingResult": AccountingResult,
        "LegalResult": LegalResult,
        "SecurityResult": SecurityResult,
    }

    def __init__(self, plans: Sequence[TaskStepPlan]) -> None:
        self.plans = tuple(plans)
        validate_step_graph(self.plans)

    async def execute(
        self,
        *,
        claim_batch: ClaimBatch,
        run_node: RunNode,
        complete_node: CompleteNode,
        resume: Mapping[str, AgentResult] | None = None,
    ) -> dict[str, AgentResult]:
        remaining = {plan.step_id: plan for plan in self.plans}
        completed: dict[str, AgentResult] = {}
        if resume:
            for step_id, output in resume.items():
                plan = remaining.get(step_id)
                if plan is not None:
                    self._validate_output(plan, output)
                    del remaining[step_id]
                # Persisted checkpoint outputs for nodes outside this run are
                # already validated; they only satisfy downstream dependencies.
                completed[step_id] = output
        while remaining:
            ready = tuple(
                plan
                for plan in self.plans
                if plan.step_id in remaining
                and all(dependency in completed for dependency in plan.depends_on)
            )
            if not ready:
                raise RuntimeError("Graph executor has no ready nodes")
            await claim_batch(ready)
            executions = await asyncio.gather(
                *(self._run_with_resilience(plan, dict(completed), run_node) for plan in ready)
            )
            for plan, execution in zip(ready, executions, strict=True):
                self._validate_output(plan, execution.output)
                await complete_node(plan, execution)
                completed[plan.step_id] = execution.output
                del remaining[plan.step_id]
        return completed

    async def _run_with_resilience(
        self,
        plan: TaskStepPlan,
        completed: Mapping[str, AgentResult],
        run_node: RunNode,
    ) -> NodeExecution:
        max_attempts = max(1, plan.max_attempts)
        last_code = "NODE_FAILED"
        for attempt in range(1, max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    run_node(plan, completed), timeout=plan.timeout_seconds
                )
            except RetryableAgentError as error:
                last_code = error.code
                if attempt >= max_attempts or error.code not in plan.retryable_error_codes:
                    break
                await asyncio.sleep(plan.backoff_seconds * (2 ** (attempt - 1)))
            except TimeoutError:
                last_code = "NODE_TIMEOUT"
                if attempt >= max_attempts or "NODE_TIMEOUT" not in plan.retryable_error_codes:
                    break
                await asyncio.sleep(plan.backoff_seconds * (2 ** (attempt - 1)))
        raise NodeExecutionFailed(
            node_id=plan.node_id or plan.step_id,
            step_id=plan.step_id,
            error_code=last_code,
            attempts=max_attempts,
        )

    @classmethod
    def load_output(cls, schema: str, data: dict[str, Any]) -> AgentResult:
        """Rebuild a validated agent result from a persisted checkpoint."""

        contract = cls._output_contracts.get(schema)
        if contract is None:
            raise ModelOutputInvalidError(f"Unknown output contract: {schema}")
        return contract.model_validate(data)

    @classmethod
    def _validate_output(cls, plan: TaskStepPlan, output: AgentResult) -> None:
        contract = cls._output_contracts.get(plan.expected_output_schema)
        if contract is None:
            raise ModelOutputInvalidError(f"Unknown output contract: {plan.expected_output_schema}")
        if not isinstance(output, contract):
            raise ModelOutputInvalidError(
                f"Node {plan.step_id} returned {type(output).__name__}; "
                f"expected {plan.expected_output_schema}"
            )
