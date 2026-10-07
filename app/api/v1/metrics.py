"""Prometheus text-format metrics endpoint (TZ 9.2, 12).

Aggregates operational gauges straight from PostgreSQL on request: task
states, DLQ depth, pending approvals, provider-call latency and Consultant+
search outcomes. No third-party metrics library - the exposition format is
tiny and dependency-free.
"""

from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app.api.auth import PrincipalDependency
from app.api.dependencies import SessionDependency
from app.db.tables.approvals import ApprovalRecord
from app.db.tables.consultant_plus import ConsultantPlusSearchEventRecord
from app.db.tables.reliability import DeadLetterEntryRecord, ProviderCallRecord
from app.db.tables.sessions import RefreshTokenRecord
from app.db.tables.tasks import TaskRecord

router = APIRouter(tags=["observability"])


def _gauge(name: str, help_text: str, value: int) -> str:
    return f"# HELP {name} {help_text}\n# TYPE {name} gauge\n{name} {value}\n"


async def _task_state_counts(session: Any, company_id: str) -> dict[str, int]:
    rows = await session.execute(
        select(TaskRecord.state, func.count())
        .where(TaskRecord.company_id == company_id)
        .group_by(TaskRecord.state)
    )
    return {state: int(count) for state, count in rows.all()}


async def _provider_latency(session: Any, company_id: str) -> dict[str, tuple[int, int]]:
    """(call_count, total_latency_ms) per provider, succeeded calls only."""
    rows = await session.execute(
        select(
            ProviderCallRecord.provider,
            func.count(),
            func.coalesce(func.sum(ProviderCallRecord.latency_ms), 0),
        )
        .join(TaskRecord, ProviderCallRecord.task_id == TaskRecord.id)
        .where(
            ProviderCallRecord.status == "succeeded",
            TaskRecord.company_id == company_id,
        )
        .group_by(ProviderCallRecord.provider)
    )
    return {provider: (int(count), int(total)) for provider, count, total in rows.all()}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(
    principal: PrincipalDependency,
    session: SessionDependency,
) -> PlainTextResponse:
    """Operational gauges in Prometheus text format, scoped to one company."""
    lines: list[str] = []

    task_counts = await _task_state_counts(session, principal.company_id)
    total_tasks = sum(task_counts.values())
    lines.append(_gauge("ai_office_tasks_total", "Tasks by state.", total_tasks))
    for state in sorted(task_counts):
        lines.append(f'ai_office_tasks_state{{state="{state}"}} {task_counts[state]}')

    unresolved_dlq = await session.scalar(
        select(func.count())
        .select_from(DeadLetterEntryRecord)
        .join(TaskRecord, DeadLetterEntryRecord.task_id == TaskRecord.id)
        .where(
            DeadLetterEntryRecord.resolved.is_(False),
            TaskRecord.company_id == principal.company_id,
        )
    )
    lines.append(
        _gauge(
            "ai_office_dlq_unresolved",
            "Dead-letter entries awaiting human review.",
            int(unresolved_dlq or 0),
        )
    )

    pending_approvals = await session.scalar(
        select(func.count())
        .select_from(ApprovalRecord)
        .join(TaskRecord, ApprovalRecord.task_id == TaskRecord.id)
        .where(
            ApprovalRecord.status == "pending",
            TaskRecord.company_id == principal.company_id,
        )
    )
    lines.append(
        _gauge(
            "ai_office_approvals_pending",
            "Approvals awaiting an OWNER decision.",
            int(pending_approvals or 0),
        )
    )

    provider_stats = await _provider_latency(session, principal.company_id)
    for provider, (count, total_ms) in sorted(provider_stats.items()):
        lines.append(
            f"# HELP ai_office_provider_calls_total Calls per provider.\n"
            f"# TYPE ai_office_provider_calls_total counter\n"
            f'ai_office_provider_calls_total{{provider="{provider}"}} {count}\n'
            f"# HELP ai_office_provider_latency_ms_sum Total latency per provider.\n"
            f"# TYPE ai_office_provider_latency_ms_sum counter\n"
            f'ai_office_provider_latency_ms_sum{{provider="{provider}"}} {total_ms}'
        )

    consultant_events = await session.scalar(
        select(func.count())
        .select_from(ConsultantPlusSearchEventRecord)
        .join(TaskRecord, ConsultantPlusSearchEventRecord.task_id == TaskRecord.id)
        .where(TaskRecord.company_id == principal.company_id)
    )
    lines.append(
        _gauge(
            "ai_office_consultant_search_events_total",
            "Mandatory Consultant+ search events (LEG-008).",
            int(consultant_events or 0),
        )
    )

    active_sessions = await session.scalar(
        select(func.count())
        .select_from(RefreshTokenRecord)
        .where(
            RefreshTokenRecord.revoked_at.is_(None),
            RefreshTokenRecord.company_id == principal.company_id,
        )
    )
    lines.append(
        _gauge(
            "ai_office_sessions_active", "Refresh tokens not revoked.", int(active_sessions or 0)
        )
    )

    return PlainTextResponse("\n".join(lines) + "\n")
