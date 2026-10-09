from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.accounting.reports import financial_report
from app.agents.accountant import AccountantAgent
from app.api.auth import OwnerDependency, PrincipalDependency, WriterDependency
from app.api.dependencies import AccountingProviderDependency, SessionDependency
from app.db.tables.accounting_sync import AccountingSyncRecord
from app.db.tables.approvals import ApprovalRecord, AuditRecord, DraftRecord
from app.db.tables.tasks import TaskRecord, TaskStepRecord
from app.models.accounting import (
    AccountBalance,
    AccountingResult,
    Counterparty,
    Invoice,
    Payment,
    Receivable,
    ReceivableReceipt,
)
from app.models.finance import FinanceReport, ReportRequest
from app.models.task import TaskResponse
from app.services.accounting_sync import SyncRequest, SyncResponse, sync_snapshot
from app.services.approvals import decide_approval
from app.services.tasks import TaskService

router = APIRouter(tags=["office"])


@router.post("/accounting/sync", response_model=SyncResponse)
async def accounting_sync(
    payload: SyncRequest,
    principal: WriterDependency,
    session: SessionDependency,
    provider: AccountingProviderDependency,
) -> SyncResponse:
    return await sync_snapshot(
        session,
        provider,
        owner_id=principal.user_id,
        request_key=payload.request_key,
        company_id=principal.company_id,
    )


@router.get("/accounting/sync-runs", response_model=list[SyncResponse])
async def accounting_sync_runs(
    principal: PrincipalDependency,
    session: SessionDependency,
) -> list[SyncResponse]:
    records = await session.scalars(
        select(AccountingSyncRecord)
        .where(
            AccountingSyncRecord.owner_id == principal.user_id,
            AccountingSyncRecord.company_id == principal.company_id,
        )
        .order_by(AccountingSyncRecord.created_at.desc())
        .limit(100)
    )
    return [SyncResponse.model_validate(record) for record in records]


@router.post("/accounting/financial-report", response_model=FinanceReport)
async def financial_report_endpoint(
    payload: ReportRequest,
    principal: PrincipalDependency,
    provider: AccountingProviderDependency,
) -> FinanceReport:
    # Read-only calculation, including for viewers; no budget or provider writes.
    return financial_report(provider, payload)


@router.get("/me")
async def me(principal: PrincipalDependency) -> dict[str, str]:
    identity = principal.model_dump()
    return {key: value for key, value in identity.items() if value is not None}


@router.get("/accounting/status")
async def accounting_status(
    principal: PrincipalDependency, provider: AccountingProviderDependency
) -> dict[str, Any]:
    return {
        "provider": provider.__class__.__name__,
        "dataset": provider.dataset_version,
        "capabilities": {"read": True, "real_write": False},
        "counts": {
            "counterparties": len(provider.list_counterparties()),
            "contracts": len(provider.list_contracts()),
            "invoices": len(provider.list_invoices()),
            "payments": len(provider.list_payments()),
            "transactions": len(provider.list_transactions()),
            "account_balances": len(provider.list_accounts()),
            "receivables": len(provider.list_receivables()),
            "receivable_receipts": len(provider.list_receivable_receipts()),
        },
    }


@router.get("/accounting/invoices")
async def invoices(
    principal: PrincipalDependency, provider: AccountingProviderDependency
) -> list[Invoice]:
    return list(provider.list_invoices())


@router.get("/accounting/counterparties")
async def counterparties(
    principal: PrincipalDependency, provider: AccountingProviderDependency
) -> list[Counterparty]:
    return list(provider.list_counterparties())


@router.get("/accounting/payments")
async def payments(
    principal: PrincipalDependency, provider: AccountingProviderDependency
) -> list[Payment]:
    return list(provider.list_payments())


@router.get("/accounting/account-balances")
async def account_balances(
    principal: PrincipalDependency, provider: AccountingProviderDependency
) -> list[AccountBalance]:
    return list(provider.list_accounts())


@router.get("/accounting/receivables")
async def receivables(
    principal: PrincipalDependency, provider: AccountingProviderDependency
) -> list[Receivable]:
    return list(provider.list_receivables())


@router.get("/accounting/receivable-receipts")
async def receivable_receipts(
    principal: PrincipalDependency, provider: AccountingProviderDependency
) -> list[ReceivableReceipt]:
    return list(provider.list_receivable_receipts())


@router.get("/accounting/report")
async def report(
    principal: PrincipalDependency,
    provider: AccountingProviderDependency,
    as_of: date,
    invoice_id: str | None = None,
) -> AccountingResult:
    return AccountantAgent(provider).execute(invoice_id=invoice_id, as_of=as_of)


@router.get("/tasks")
async def list_tasks(
    principal: PrincipalDependency,
    session: SessionDependency,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[TaskResponse]:
    tasks = await session.scalars(
        select(TaskRecord)
        .where(
            TaskRecord.user_id == principal.user_id,
            TaskRecord.company_id == principal.company_id,
        )
        .order_by(TaskRecord.created_at.desc())
        .limit(limit)
    )
    return [TaskService.to_response(task) for task in tasks]


@router.get("/tasks/{task_id}/trace")
async def trace(
    task_id: str,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> dict[str, Any]:
    task = await session.get(TaskRecord, task_id)
    if task is None or task.user_id != principal.user_id or task.company_id != principal.company_id:
        raise HTTPException(404, "Task not found")
    steps = await session.scalars(
        select(TaskStepRecord)
        .where(
            TaskStepRecord.task_id == task_id,
        )
        .order_by(TaskStepRecord.started_at, TaskStepRecord.id)
    )
    events = await session.scalars(
        select(AuditRecord)
        .where(
            AuditRecord.task_id == task_id,
            AuditRecord.owner_id == principal.user_id,
            AuditRecord.company_id == principal.company_id,
        )
        .order_by(AuditRecord.created_at)
    )
    return {
        "trace_id": task.trace_id,
        "task_id": task_id,
        "steps": [
            {
                "id": s.id,
                "node_id": s.node_id,
                "agent": s.agent_type,
                "state": s.state,
                "attempt": s.attempt,
                "depends_on": s.depends_on,
                "started_at": s.started_at,
                "completed_at": s.completed_at,
                "error_code": s.error_code,
            }
            for s in steps
        ],
        "audit": [
            {"id": e.id, "event": e.event, "details": e.details, "created_at": e.created_at}
            for e in events
        ],
    }


@router.get("/activity")
async def activity(
    principal: PrincipalDependency,
    session: SessionDependency,
    limit: int = Query(default=100, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
) -> dict[str, list[dict[str, Any]]]:
    """Return an owner-scoped activity feed assembled from persisted records."""

    audits = await session.scalars(
        select(AuditRecord)
        .where(
            AuditRecord.owner_id == principal.user_id,
            AuditRecord.company_id == principal.company_id,
        )
        .order_by(AuditRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    step_rows = await session.execute(
        select(TaskStepRecord, TaskRecord.trace_id)
        .join(TaskRecord, TaskStepRecord.task_id == TaskRecord.id)
        .where(
            TaskRecord.user_id == principal.user_id,
            TaskRecord.company_id == principal.company_id,
        )
        .order_by(TaskStepRecord.completed_at.desc(), TaskStepRecord.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "audit": [
            {
                "id": event.id,
                "task_id": event.task_id,
                "event": event.event,
                "details": event.details,
                "created_at": event.created_at,
            }
            for event in audits
        ],
        "steps": [
            {
                "id": step.id,
                "task_id": step.task_id,
                "trace_id": trace_id,
                "node_id": step.node_id,
                "agent": step.agent_type,
                "state": step.state,
                "attempt": step.attempt,
                "started_at": step.started_at,
                "completed_at": step.completed_at,
                "error_code": step.error_code,
            }
            for step, trace_id in step_rows
        ],
    }


@router.get("/approvals")
async def approvals(
    principal: PrincipalDependency,
    session: SessionDependency,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    records = await session.scalars(
        select(ApprovalRecord)
        .where(
            ApprovalRecord.owner_id == principal.user_id,
            ApprovalRecord.company_id == principal.company_id,
        )
        .order_by(ApprovalRecord.expires_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        {
            "id": r.id,
            "task_id": r.task_id,
            "status": r.status,
            "payload": r.payload,
            "payload_hash": r.payload_hash,
            "expires_at": r.expires_at,
        }
        for r in records
    ]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]


@router.post("/approvals/{approval_id}/decision")
async def decision(
    approval_id: str,
    payload: DecisionRequest,
    principal: OwnerDependency,
    session: SessionDependency,
) -> TaskResponse:
    task = await decide_approval(
        session,
        approval_id,
        owner_id=principal.user_id,
        approve=payload.decision == "approve",
        company_id=principal.company_id,
    )
    return TaskService.to_response(task)


@router.get("/drafts")
async def drafts(
    principal: PrincipalDependency,
    session: SessionDependency,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    records = await session.scalars(
        select(DraftRecord)
        .where(
            DraftRecord.owner_id == principal.user_id,
            DraftRecord.company_id == principal.company_id,
        )
        .order_by(DraftRecord.created_at.desc())
        .limit(limit)
    )
    return [
        {"id": r.id, "approval_id": r.approval_id, "payload": r.payload, "created_at": r.created_at}
        for r in records
    ]
