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
