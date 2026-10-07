import asyncio
from datetime import UTC, datetime

import pytest

from app.core.exceptions import (
    ModelOutputInvalidError,
    NodeExecutionFailed,
    RetryableAgentError,
    RunBudgetExceededError,
)
from app.models.agent import AgentResult
from app.models.enums import AgentType, RiskLevel
from app.models.task import TaskStepPlan
from app.orchestrator.budget import reserve_node
from app.orchestrator.contracts import RunBudget, RunUsage
from app.orchestrator.graph import GraphExecutor, NodeExecution


def plan(
    step_id: str,
    *,
    depends_on: list[str] | None = None,
    schema: str = "AgentResult",
) -> TaskStepPlan:
    return TaskStepPlan(
        step_id=step_id,
        agent=AgentType.SECURITY,
        action="security_preflight",
        depends_on=depends_on or [],
        risk_level=RiskLevel.LOW,
        expected_output_schema=schema,
    )


async def test_executor_claims_and_runs_independent_roots_together() -> None:
    plans = [
        plan("accounting"),
        plan("security"),
        plan("postflight", depends_on=["accounting", "security"]),
    ]
    claimed: list[tuple[str, ...]] = []
    completed: list[str] = []
    roots_started: list[str] = []
    both_roots_started = asyncio.Event()

    async def claim(batch: tuple[TaskStepPlan, ...]) -> None:
        claimed.append(tuple(item.step_id for item in batch))

    async def run(item: TaskStepPlan, _outputs: dict[str, AgentResult]) -> NodeExecution:
        if item.step_id in {"accounting", "security"}:
            roots_started.append(item.step_id)
            if len(roots_started) == 2:
                both_roots_started.set()
            await asyncio.wait_for(both_roots_started.wait(), timeout=1)
        return NodeExecution(
            output=AgentResult(agent=AgentType.SECURITY, status="ok", summary=item.step_id),
            latency_ms=1,
        )

    async def finish(item: TaskStepPlan, _execution: NodeExecution) -> None:
        completed.append(item.step_id)

    outputs = await GraphExecutor(plans).execute(
        claim_batch=claim,
        run_node=run,
        complete_node=finish,
    )

    assert claimed == [("accounting", "security"), ("postflight",)]
    assert completed == ["accounting", "security", "postflight"]
    assert set(outputs) == {"accounting", "security", "postflight"}


async def test_executor_rejects_output_that_breaks_node_contract() -> None:
    async def claim(_batch: tuple[TaskStepPlan, ...]) -> None:
        return None

    async def run(_item: TaskStepPlan, _outputs: dict[str, AgentResult]) -> NodeExecution:
        return NodeExecution(
            output=AgentResult(agent=AgentType.SECURITY, status="ok", summary="not security"),
            latency_ms=1,
        )

    async def finish(_item: TaskStepPlan, _execution: NodeExecution) -> None:
        return None

    with pytest.raises(ModelOutputInvalidError, match="expected SecurityResult"):
        await GraphExecutor([plan("only", schema="SecurityResult")]).execute(
            claim_batch=claim,
            run_node=run,
            complete_node=finish,
        )


def test_budget_reserves_declared_capacity_before_a_node_starts() -> None:
    budget = RunBudget(max_steps=1, max_llm_calls=0, max_cost_rub="0")
    first = reserve_node(budget, RunUsage(), plan("one"), now=datetime.now(UTC))
    assert first.steps_started == 1
    with pytest.raises(RunBudgetExceededError, match="RUN_STEP_LIMIT_REACHED"):
        reserve_node(budget, first, plan("two"), now=datetime.now(UTC))


def retry_plan(
    step_id: str,
    *,
    max_attempts: int = 2,
    retryable: tuple[str, ...] = ("PROVIDER_BUSY",),
    timeout: int = 5,
    backoff: float = 0.0,
) -> TaskStepPlan:
    base = plan(step_id)
    return base.model_copy(
        update={
            "max_attempts": max_attempts,
            "retryable_error_codes": list(retryable),
            "timeout_seconds": timeout,
            "backoff_seconds": backoff,
        }
    )


async def test_retryable_node_is_retried_then_succeeds() -> None:
    calls = {"count": 0}

    async def run(item: TaskStepPlan, _outputs: dict[str, AgentResult]) -> NodeExecution:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RetryableAgentError("PROVIDER_BUSY", "provider temporarily busy")
        return NodeExecution(
            output=AgentResult(agent=AgentType.SECURITY, status="ok", summary="recovered"),
            latency_ms=1,
            attempts=2,
        )

    async def claim(_batch: tuple[TaskStepPlan, ...]) -> None:
        return None

    async def finish(_item: TaskStepPlan, _execution: NodeExecution) -> None:
        return None

    outputs = await GraphExecutor([retry_plan("node_a")]).execute(
        claim_batch=claim, run_node=run, complete_node=finish
    )
    assert calls["count"] == 2
    assert outputs["node_a"].summary == "recovered"


async def test_exhausted_retries_raise_node_execution_failed() -> None:
    calls = {"count": 0}

    async def run(_item: TaskStepPlan, _outputs: dict[str, AgentResult]) -> NodeExecution:
        calls["count"] += 1
        raise RetryableAgentError("PROVIDER_BUSY", "provider temporarily busy")

    async def claim(_batch: tuple[TaskStepPlan, ...]) -> None:
        return None

    async def finish(_item: TaskStepPlan, _execution: NodeExecution) -> None:
        return None

    with pytest.raises(NodeExecutionFailed) as info:
        await GraphExecutor([retry_plan("node_a", max_attempts=2)]).execute(
            claim_batch=claim, run_node=run, complete_node=finish
        )
    assert calls["count"] == 2
    assert info.value.error_code == "PROVIDER_BUSY"
    assert info.value.attempts == 2


async def test_non_retryable_error_stops_immediately() -> None:
    calls = {"count": 0}

    async def run(_item: TaskStepPlan, _outputs: dict[str, AgentResult]) -> NodeExecution:
        calls["count"] += 1
        raise RetryableAgentError("POLICY_DENIED", "not retryable")

    async def claim(_batch: tuple[TaskStepPlan, ...]) -> None:
        return None

    async def finish(_item: TaskStepPlan, _execution: NodeExecution) -> None:
        return None

    with pytest.raises(NodeExecutionFailed) as info:
        await GraphExecutor([retry_plan("node_a", max_attempts=3)]).execute(
            claim_batch=claim, run_node=run, complete_node=finish
        )
    assert calls["count"] == 1
    assert info.value.error_code == "POLICY_DENIED"


async def test_node_timeout_is_enforced() -> None:
    async def run(_item: TaskStepPlan, _outputs: dict[str, AgentResult]) -> NodeExecution:
        await asyncio.sleep(5)

    async def claim(_batch: tuple[TaskStepPlan, ...]) -> None:
        return None

    async def finish(_item: TaskStepPlan, _execution: NodeExecution) -> None:
        return None

    slow = retry_plan("slow_node", timeout=1, max_attempts=1)
    with pytest.raises(NodeExecutionFailed) as info:
        await GraphExecutor([slow]).execute(claim_batch=claim, run_node=run, complete_node=finish)
    assert info.value.error_code == "NODE_TIMEOUT"


async def test_resume_skips_confirmed_nodes_and_satisfies_dependencies() -> None:
    downstream_calls = {"count": 0}

    async def run(_item: TaskStepPlan, outputs: dict[str, AgentResult]) -> NodeExecution:
        downstream_calls["count"] += 1
        assert "root" in outputs, "downstream must see the resumed root output"
        return NodeExecution(
            output=AgentResult(agent=AgentType.SECURITY, status="ok", summary="child"),
            latency_ms=1,
        )

    async def claim(_batch: tuple[TaskStepPlan, ...]) -> None:
        return None

    async def finish(_item: TaskStepPlan, _execution: NodeExecution) -> None:
        return None

    resumed_root = AgentResult(agent=AgentType.SECURITY, status="ok", summary="from checkpoint")
    outputs = await GraphExecutor(
        [
            plan("root"),
            retry_plan("child", retryable=()),
        ]
    ).execute(
        claim_batch=claim,
        run_node=run,
        complete_node=finish,
        resume={"root": resumed_root},
    )
    assert outputs["root"] is resumed_root
    assert outputs["child"].summary == "child"
    assert downstream_calls["count"] == 1
