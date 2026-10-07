import asyncio
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.approvals import ApprovalRecord, AuditRecord, DraftRecord
from app.main import create_app


@pytest.mark.parametrize("second_action", ["cancel", "approve"])
async def test_cancellation_has_one_consistent_outcome(
    pg_engine: AsyncEngine,
    tmp_path: Path,
    second_action: str,
):
    factory = create_session_factory(pg_engine)
    app = create_app(
        settings=Settings(app_env="test", upload_dir=tmp_path),
        engine=pg_engine,
        session_factory=factory,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
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
            task_id = created.json()["task_id"]
            approval_id = created.json()["result"]["approval_id"]
            cancel_path = f"/api/v1/tasks/{task_id}/cancel"
            first, second = await asyncio.gather(
                client.post(cancel_path),
                client.post(cancel_path)
                if second_action == "cancel"
                else client.post(
                    f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}
                ),
            )
            final = (await client.get(f"/api/v1/tasks/{task_id}")).json()
            async with factory() as session:
                approval = await session.get(ApprovalRecord, approval_id)
                drafts = await session.scalar(select(func.count()).select_from(DraftRecord))
                cancelled_events = await session.scalar(
                    select(func.count())
                    .select_from(AuditRecord)
                    .where(AuditRecord.event == "task_cancelled")
                )
                if final["state"] == "cancelled":
                    assert first.status_code == 200
                    assert second.status_code == (200 if second_action == "cancel" else 409)
                    assert approval.status == "cancelled"
                    assert drafts == 0
                    assert cancelled_events == 1
                    assert final["result"]["requires_approval"] is False
                else:
                    assert second_action == "approve"
                    assert first.status_code == 409 and second.status_code == 200
                    assert approval.status == "approved" and drafts == 1
                    assert cancelled_events == 0
