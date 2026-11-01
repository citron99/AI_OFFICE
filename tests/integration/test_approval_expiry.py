from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.db.tables.approvals import ApprovalRecord, AuditRecord, DraftRecord
from app.services.approvals import expire_pending_approvals


async def test_housekeeping_expires_once_without_user_action(
    client: httpx.AsyncClient, engine: AsyncEngine
):
    created = await client.post(
        "/api/v1/tasks",
        json={
            "message": "invoice",
            "invoice_id": "inv_101",
            "requested_action": "prepare_payment_draft",
            "effective_on": "2026-08-27",
        },
    )
    assert created.status_code == 201
    task = created.json()
    approval_id = task["result"]["approval_id"]
    async with create_session_factory(engine)() as session:
        assert await expire_pending_approvals(session) == 0  # Still valid.
        approval = await session.get(ApprovalRecord, approval_id)
        approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        assert await expire_pending_approvals(session) == 1
        assert await expire_pending_approvals(session) == 0
        assert await session.scalar(select(func.count()).select_from(DraftRecord)) == 0
        events = await session.scalars(
            select(AuditRecord).where(AuditRecord.event == "approval_expired")
        )
        assert len(list(events)) == 1
    updated = (await client.get(f"/api/v1/tasks/{task['task_id']}")).json()
    assert updated["state"] == "completed"
    assert updated["result"]["status"] == "approval_expired"
    assert updated["result"]["requires_approval"] is False
    assert (
        await client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"})
    ).status_code == 409


async def test_approve_after_ceiling_lowered_is_blocked_but_reject_stays_safe(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """TZ 7.1 / REL-006: an approval cleared when the task started must not outlive
    the runtime ceiling. If the OWNER lowers office_review below A2 during the TTL,
    the approve path re-checks get_runtime and refuses the draft, while declining
    (reject) stays allowed because it produces no write."""
    draft_payload = {
        "message": "invoice",
        "invoice_id": "inv_101",  # above the established limit -> owner approval
        "requested_action": "prepare_payment_draft",
        "effective_on": "2026-08-27",
    }
    first = await client.post("/api/v1/tasks", json=draft_payload)
    assert first.status_code == 201
    approval_a = first.json()["result"]["approval_id"]
    second = await client.post(
        "/api/v1/tasks",
        json=draft_payload,
        headers={"Idempotency-Key": "gate-second"},
    )
    assert second.status_code == 201
    approval_b = second.json()["result"]["approval_id"]

    lowered = await client.post(
        "/api/v1/processes/office_review/runtime",
        json={"autonomy_level": "a1_recommendation"},
    )
    assert lowered.status_code == 200

    blocked = await client.post(
        f"/api/v1/approvals/{approval_a}/decision", json={"decision": "approve"}
    )
    assert blocked.status_code == 409
    declined = await client.post(
        f"/api/v1/approvals/{approval_b}/decision", json={"decision": "reject"}
    )
    assert declined.status_code == 200

    async with create_session_factory(engine)() as session:
        assert await session.scalar(select(func.count()).select_from(DraftRecord)) == 0
        assert (await session.get(ApprovalRecord, approval_a)).status == "invalidated"
        assert (await session.get(ApprovalRecord, approval_b)).status == "rejected"
        gate_events = await session.scalars(
            select(AuditRecord).where(AuditRecord.event == "approval_invalidated_gate")
        )
        assert len(list(gate_events)) == 1
