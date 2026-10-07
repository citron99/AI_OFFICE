from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.approvals import AuditRecord
from app.db.tables.tasks import TaskRecord
from app.main import create_app


@pytest.mark.parametrize("failure", [False, True])
async def test_queue_sends_only_id_and_persists_safe_state(
    engine: AsyncEngine,
    tmp_path: Path,
    monkeypatch,
    failure: bool,
) -> None:
    from app import jobs

    sent = []

    def publish(task_id: str) -> None:
        sent.append(task_id)
        if failure:
            raise OSError("private broker credentials")

    monkeypatch.setattr(jobs, "publish", publish)
    settings = Settings(app_env="test", execution_mode="queue", upload_dir=tmp_path)
    factory = create_session_factory(engine)
    app = create_app(settings=settings, engine=engine, session_factory=factory)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/tasks",
                json={
                    "message": "security password=SYNTHETIC-secret",
                    "requested_agent": "security",
                },
            )
            assert response.status_code == 201
            body = response.json()
            assert sent == [body["task_id"]]
            assert body["state"] == ("failed" if failure else "queued")
            assert "private broker" not in response.text
            async with factory() as session:
                record = await session.scalar(select(TaskRecord))
                assert record is not None
                assert "SYNTHETIC-secret" not in str(record.request_data)
                assert "[REDACTED:PASSWORD]" in record.input_text
            if failure:
                retry = await client.post(
                    f"/api/v1/tasks/{body['task_id']}/retry",
                    headers={"Idempotency-Key": "retry-network-attempt"},
                )
                assert retry.status_code == 201
                assert retry.json()["task_id"] != body["task_id"]
                assert len(sent) == 2
                repeated = await client.post(
                    f"/api/v1/tasks/{body['task_id']}/retry",
                    headers={"Idempotency-Key": "retry-network-attempt"},
                )
                assert repeated.status_code == 201
                assert repeated.json()["task_id"] == retry.json()["task_id"]
                assert len(sent) == 2
                async with factory() as session:
                    assert await session.scalar(select(func.count()).select_from(TaskRecord)) == 2
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(AuditRecord)
                            .where(AuditRecord.event == "task_retried")
                        )
                        == 1
                    )
            else:
                assert (
                    await client.post(f"/api/v1/tasks/{body['task_id']}/retry")
                ).status_code == 409
