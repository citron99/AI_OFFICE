import asyncio
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.approvals import DraftRecord
from app.main import create_app


async def test_concurrent_approval_produces_one_draft(
    pg_engine: AsyncEngine, tmp_path: Path
) -> None:
    factory = create_session_factory(pg_engine)
    app = create_app(
        settings=Settings(app_env="test", upload_dir=tmp_path),
        engine=pg_engine,
        session_factory=factory,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
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
            assert created.status_code == 201, created.text
            approval = created.json()["result"]["approval_id"]
            responses = await asyncio.gather(
                *[
                    client.post(
                        "/api/v1/approvals/" + approval + "/decision", json={"decision": "approve"}
                    )
                    for _ in range(2)
                ]
            )
            assert all(r.status_code == 200 for r in responses)
            assert responses[0].json() == responses[1].json()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(DraftRecord)) == 1
