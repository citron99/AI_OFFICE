"""Office node executors: one registered function per graph action (TZ 3.3).

Adding a node means registering an executor here — TaskService no longer
branches on action strings. Executors receive an explicit ``OfficeRunContext``
and return the node's typed result; grant enforcement and timing stay in the
graph loop (TaskService), data access happens here.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.accounting.provider import AccountingProvider
from app.agents.accountant import AccountantAgent
from app.agents.lawyer import LawyerAgent
from app.agents.security import SecurityAgent
from app.integrations.consultant_plus.factory import ConsultantPlusProviderLike
from app.models.accounting import AccountingResult
from app.models.agent import AgentResult
from app.models.digest import NonpaymentRisk  # noqa: F401  (result payloads)
from app.models.legal import LegalResult
from app.models.office import SecurityResult
from app.models.task import TaskStepPlan


@dataclass(frozen=True, slots=True)
class OfficeRunContext:
    """Everything a node executor may touch; nothing else is passed."""

    accounting_provider: AccountingProvider
    lawyer_agent: LawyerAgent | None
    consultant: ConsultantPlusProviderLike | None
    security_agent: SecurityAgent
    # DocumentExcerpt list, pre-extracted attachments.
    documents: list[Any]
    message: str
    invoice_id: str | None
    jurisdiction: str | None
    effective_on: date | None
    attachment_ids: list[str]
    requested_action: str
    user_id: str
    company_id: str
    as_of: date


def result_for_action(
    plans: list[TaskStepPlan],
    outputs: Mapping[str, AgentResult],
    action: str,
) -> AgentResult | None:
    for plan in plans:
        if plan.action == action:
            return outputs.get(plan.step_id)
    # Resumed checkpoint outputs are aliased by node id and action.
    return outputs.get(action)


def result_for_node_id(
    plans: list[TaskStepPlan],
    outputs: Mapping[str, AgentResult],
    node_id: str,
) -> AgentResult | None:
    for plan in plans:
        if plan.node_id == node_id:
            return outputs.get(plan.step_id)
    return outputs.get(node_id)


def alias_outputs(
    outputs: Mapping[str, AgentResult],
    step_ids: Mapping[str, str],
    specs: Mapping[str, Any],
) -> dict[str, AgentResult]:
    """Index outputs by step id, node id and action so resumed nodes resolve."""
    view = dict(outputs)
    for step_id, output in outputs.items():
        node_id = step_ids.get(step_id)
        if node_id is None:
            continue
        view[node_id] = output
        spec = specs.get(node_id)
        if spec is not None:
            view[spec.action] = output
    return view


async def run_accounting_node(
    ctx: OfficeRunContext,
    _plan: TaskStepPlan,
    _completed: dict[str, AgentResult],
    _plans: list[TaskStepPlan],
) -> AgentResult:
    result: AgentResult = await _to_thread(
        AccountantAgent(ctx.accounting_provider).execute,
        invoice_id=ctx.invoice_id,
        as_of=ctx.as_of,
    )
    return result


async def run_cash_control_node(
    ctx: OfficeRunContext,
    _plan: TaskStepPlan,
    _completed: dict[str, AgentResult],
    _plans: list[TaskStepPlan],
) -> AgentResult:
    # Aggregate cash flows without invoice-level checks: the cash half of the
    # daily digest.
    result: AgentResult = await _to_thread(
        AccountantAgent(ctx.accounting_provider).execute,
        invoice_id=None,
        as_of=ctx.as_of,
    )
    return result


async def run_receivable_risk_node(
    ctx: OfficeRunContext,
    _plan: TaskStepPlan,
    _completed: dict[str, AgentResult],
    _plans: list[TaskStepPlan],
) -> AgentResult:
    # Deterministic receivables aging and non-payment risks.
    result: AgentResult = await _to_thread(
        AccountantAgent(ctx.accounting_provider).analyze_receivables,
        as_of=ctx.as_of,
    )
    return result


async def run_security_preflight_node(
    ctx: OfficeRunContext,
    _plan: TaskStepPlan,
    _completed: dict[str, AgentResult],
    _plans: list[TaskStepPlan],
) -> AgentResult:
    result: AgentResult = await _to_thread(
        ctx.security_agent.execute,
        [ctx.message, *(part.text for part in ctx.documents)],
    )
    return result


async def run_legal_node(
    ctx: OfficeRunContext,
    _plan: TaskStepPlan,
    completed: dict[str, AgentResult],
    _plans: list[TaskStepPlan],
) -> AgentResult:
    preflight = result_for_action(_plans, completed, "security_preflight")
    if not isinstance(preflight, SecurityResult):
        raise RuntimeError("Legal node requires completed security preflight")
    assert ctx.lawyer_agent is not None
    lawyer = LawyerAgent(
        ctx.lawyer_agent.knowledge,
        None if preflight.detections else ctx.lawyer_agent.provider,
        consultant=None if preflight.detections else ctx.consultant,
    )
    component = await lawyer.execute(
        text=ctx.message,
        user_id=ctx.user_id,
        company_id=ctx.company_id,
        jurisdiction=ctx.jurisdiction,
        effective_on=ctx.effective_on,
        artifact_ids=ctx.attachment_ids,
    )
    if preflight.detections:
        component.warnings.append("EXTERNAL_ANALYSIS_BLOCKED_BY_SECURITY")
    return component


async def run_security_postflight_node(
    ctx: OfficeRunContext,
    _plan: TaskStepPlan,
    completed: dict[str, AgentResult],
    plans: list[TaskStepPlan],
) -> AgentResult:
    preflight = result_for_action(plans, completed, "security_preflight")
    accounting = result_for_node_id(plans, completed, "accounting_snapshot")
    legal = result_for_action(plans, completed, "lawyer_pilot")
    if not isinstance(preflight, SecurityResult):
        raise RuntimeError("Postflight node requires completed security preflight")
    result: AgentResult = await _to_thread(
        ctx.security_agent.postflight,
        preflight=preflight,
        accounting=accounting if isinstance(accounting, AccountingResult) else None,
        legal=legal if isinstance(legal, LegalResult) else None,
        requested_action=ctx.requested_action,
    )
    return result


NodeExecutor = Callable[
    [OfficeRunContext, TaskStepPlan, dict[str, AgentResult], list[TaskStepPlan]],
    Awaitable[AgentResult],
]

NODE_EXECUTORS: dict[str, NodeExecutor] = {
    "accountant_pilot": run_accounting_node,
    "accounting_snapshot": run_accounting_node,
    "cash_control": run_cash_control_node,
    "receivable_risk": run_receivable_risk_node,
    "security_preflight": run_security_preflight_node,
    "lawyer_pilot": run_legal_node,
    "security_postflight": run_security_postflight_node,
}


async def _to_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(fn, *args, **kwargs)
