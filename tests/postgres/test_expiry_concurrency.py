import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.approvals import ApprovalRecord, AuditRecord, DraftRecord
from app.main import create_app
from app.services.approvals import expire_pending_approvals


async def test_expiry_races_with_decision_without_draft(pg_engine: AsyncEngine, tmp_path: Path):
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
            approval_id = created.json()["result"]["approval_id"]
            async with factory() as session:
                record = await session.get(ApprovalRecord, approval_id)
                record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()

            async def sweep():
                async with factory() as session:
                    return await expire_pending_approvals(session)

            first, second, decision = await asyncio.gather(
                sweep(),
                sweep(),
                client.post(
                    f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}
                ),
            )
            assert first + second <= 1
            assert decision.status_code == 409
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(DraftRecord)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditRecord)
                .where(AuditRecord.event == "approval_expired")
            )
            == 1
        )
        assert (await session.get(ApprovalRecord, approval_id)).status == "expired"
