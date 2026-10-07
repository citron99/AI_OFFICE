import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables.approvals import ApprovalRecord, AuditRecord, DraftRecord
from app.db.tables.tasks import TaskRecord
from app.models.office import OfficeResult


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def audit(session: AsyncSession, task: TaskRecord, event: str, details: dict[str, Any]) -> None:
    # Only structured IDs/decisions here: never raw prompts, documents or bank details.
    session.add(
        AuditRecord(
            company_id=task.company_id,
            owner_id=task.user_id,
            task_id=task.id,
            event=event,
            details=details,
        )
    )


async def request_approval(
    session: AsyncSession,
    task: TaskRecord,
    result: OfficeResult,
) -> ApprovalRecord:
    assert result.accounting and result.accounting.invoice
    invoice = result.accounting.invoice
    payload = {
        "action": "create_mock_payment_draft",
        "invoice_id": invoice.id,
        "amount": str(result.accounting.outstanding),
        "currency": invoice.currency,
        "bank_fingerprint": invoice.bank_fingerprint,
        "dataset_version": result.accounting.dataset_version,
        "policy_version": result.policy_version,
        "legal_clearance": False,
        "real_payment_allowed": False,
    }
    record = ApprovalRecord(
        company_id=task.company_id,
        task_id=task.id,
        owner_id=task.user_id,
        payload=payload,
        payload_hash=payload_hash(payload),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        policy_version=result.policy_version,
        requested_by="orchestrator",
    )
    session.add(record)
    await session.flush()
    audit(
        session,
        task,
        "approval_requested",
        {"approval_id": record.id, "payload_hash": record.payload_hash},
    )
    return record


async def decide_approval(
    session: AsyncSession,
    approval_id: str,
    *,
    owner_id: str,
    approve: bool,
    company_id: str = "comp_demo",
) -> TaskRecord:
    # Lock order is task -> approval in all mutating paths.
    preview = await session.get(ApprovalRecord, approval_id)
    if preview is None or preview.owner_id != owner_id:
        raise HTTPException(404, "Approval not found")
    task = await session.scalar(
        select(TaskRecord)
        .where(
            TaskRecord.id == preview.task_id,
            TaskRecord.user_id == owner_id,
            TaskRecord.company_id == company_id,
        )
        .with_for_update()
    )
    record = await session.scalar(
        select(ApprovalRecord)
        .where(ApprovalRecord.id == approval_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None or record is None:
        raise HTTPException(404, "Approval not found")
    target = "approved" if approve else "rejected"
    if record.status == target:
        return task
    if record.status != "pending" or task.state != "waiting_approval":
        raise HTTPException(409, "Approval is not pending")
    now = datetime.now(UTC)
    expiry = (
        record.expires_at.replace(tzinfo=UTC)
        if record.expires_at.tzinfo is None
        else record.expires_at
    )
    if expiry <= now:
        _expire_locked(session, task, record, now)
        await session.commit()
        raise HTTPException(409, "Approval expired; create a new task")
    if record.payload_hash != payload_hash(record.payload):
        # APR-005: a changed payload invalidates the approval instead of failing silently.
        record.status = "invalidated"
        record.invalidated_at = now
        audit(session, task, "approval_invalidated", {"approval_id": record.id})
        await session.commit()
        raise HTTPException(409, "Approval payload changed; request invalidated")
    changed = await session.execute(
        update(ApprovalRecord)
        .where(
            ApprovalRecord.id == approval_id,
            ApprovalRecord.status == "pending",
            ApprovalRecord.expires_at > now,
        )
        .values(status=target, decided_at=now, decision_reason=f"owner_decided_{target}")
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult[Any], changed).rowcount != 1:
        raise HTTPException(409, "Approval already decided")
    result = OfficeResult.model_validate(task.result)
    if approve:
        draft = DraftRecord(
            company_id=task.company_id,
            approval_id=record.id,
            owner_id=owner_id,
            payload=record.payload,
        )
        session.add(draft)
        await session.flush()
        result.draft_id = draft.id
        result.status = "mock_draft_created"
        result.summary = "Создан только синтетический черновик. Платёж не выполнялся."
    else:
        result.status = "draft_rejected"
        result.summary = "Создание черновика отклонено."
    result.requires_approval = False
    task.result = result.model_dump(mode="json")
    task.state = "completed"
    task.completed_at = task.updated_at = now
    audit(
        session, task, f"approval_{target}", {"approval_id": record.id, "draft_id": result.draft_id}
    )
    await session.commit()
    return task


def _expire_locked(
    session: AsyncSession,
    task: TaskRecord,
    record: ApprovalRecord,
    now: datetime,
) -> None:
    result = OfficeResult.model_validate(task.result)
    result.status = "approval_expired"
    result.requires_approval = False
    result.summary = "Срок согласования истёк. Черновик не создан; требуется новая проверка."
    record.status = "expired"
    record.decided_at = now
    task.result = result.model_dump(mode="json")
    task.state = "completed"
    task.completed_at = task.updated_at = now
    audit(session, task, "approval_expired", {"approval_id": record.id})


async def expire_pending_approvals(session: AsyncSession, *, limit: int = 100) -> int:
    """Bounded housekeeping, using the same task -> approval lock order as decisions."""
    if not 1 <= limit <= 100:
        raise ValueError("Expiry batch limit must be between 1 and 100")
    cutoff = datetime.now(UTC)
    candidates = list(
        (
            await session.execute(
                select(ApprovalRecord.id, ApprovalRecord.task_id)
                .join(TaskRecord, TaskRecord.id == ApprovalRecord.task_id)
                .where(
                    ApprovalRecord.status == "pending",
                    ApprovalRecord.expires_at <= cutoff,
                    TaskRecord.state == "waiting_approval",
                    TaskRecord.user_id == ApprovalRecord.owner_id,
                )
                .order_by(ApprovalRecord.expires_at, ApprovalRecord.id)
                .limit(limit)
            )
        ).all()
    )
    expired = 0
    for approval_id, task_id in candidates:
        task = await session.scalar(
            select(TaskRecord)
            .where(TaskRecord.id == task_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if task is None or task.state != "waiting_approval":
            await session.rollback()
            continue
        record = await session.scalar(
            select(ApprovalRecord)
            .where(ApprovalRecord.id == approval_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record is not None and record.owner_id == task.user_id and record.status == "pending":
            expiry = record.expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry <= cutoff:
                _expire_locked(session, task, record, cutoff)
                expired += 1
        await session.commit()
    return expired
