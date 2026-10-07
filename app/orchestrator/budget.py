"""Run-budget accounting used by the graph scheduler before every node claim."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.core.exceptions import RunBudgetExceededError
from app.models.task import TaskStepPlan
from app.orchestrator.contracts import RunBudget, RunUsage


def reserve_node(
    budget: RunBudget,
    usage: RunUsage,
    plan: TaskStepPlan,
    *,
    now: datetime,
) -> RunUsage:
    """Reserve the declared capacity before a node is allowed to start."""

    moment = now.astimezone(UTC)
    current = usage.model_copy(update={"started_at": usage.started_at or moment}, deep=True)
    if current.runtime_seconds(moment) >= budget.max_runtime_seconds:
        raise RunBudgetExceededError("RUN_RUNTIME_LIMIT_REACHED")
    if current.rework_cycles > budget.max_rework_cycles:
        raise RunBudgetExceededError("RUN_REWORK_LIMIT_REACHED")
    if current.steps_started + 1 > budget.max_steps:
        raise RunBudgetExceededError("RUN_STEP_LIMIT_REACHED")
    if current.input_tokens > budget.max_input_tokens:
        raise RunBudgetExceededError("RUN_INPUT_TOKEN_LIMIT_REACHED")
    if current.output_tokens > budget.max_output_tokens:
        raise RunBudgetExceededError("RUN_OUTPUT_TOKEN_LIMIT_REACHED")
    if current.observed_cost_rub > budget.max_cost_rub:
        raise RunBudgetExceededError("RUN_COST_LIMIT_REACHED")
    if current.llm_calls + plan.estimated_llm_calls > budget.max_llm_calls:
        raise RunBudgetExceededError("RUN_LLM_CALL_LIMIT_REACHED")
    next_reserved_cost = current.reserved_cost_rub + plan.estimated_cost_rub
    if next_reserved_cost > budget.max_cost_rub:
        raise RunBudgetExceededError("RUN_COST_LIMIT_REACHED")
    return current.model_copy(
        update={
            "steps_started": current.steps_started + 1,
            "llm_calls": current.llm_calls + plan.estimated_llm_calls,
            "reserved_cost_rub": next_reserved_cost,
        }
    )


def record_model_usage(
    budget: RunBudget,
    usage: RunUsage,
    *,
    input_tokens: int,
    output_tokens: int,
    observed_cost_rub: Decimal,
) -> RunUsage:
    """Record provider telemetry; declared reservations remain the hard cap.

    Current providers may omit cost data.  In that case the process definition's
    conservative node estimate still protects the ruble budget.
    """

    updated = usage.model_copy(
        update={
            "input_tokens": usage.input_tokens + input_tokens,
            "output_tokens": usage.output_tokens + output_tokens,
            "observed_cost_rub": usage.observed_cost_rub + observed_cost_rub,
        }
    )
    return updated


def decimal_cost(value: str | None) -> Decimal:
    """Interpret provider cost only when it is a non-negative decimal amount."""

    if value is None:
        return Decimal("0")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return max(Decimal("0"), parsed)
