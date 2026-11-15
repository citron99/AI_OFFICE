"""Reliability integration: controlled fail-safe stop and checkpoint resume."""

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app import jobs
from app.agents.security import SecurityAgent
from app.config import Settings
from app.core.exceptions import RetryableAgentError
from app.db.session import create_session_factory
from app.db.tables.reliability import (
    DeadLetterEntryRecord,
    ExecutionCheckpointRecord,
    ProviderCallRecord,
)
from app.db.tables.tasks import TaskStepRecord
from app.main import create_app


async def create_draft_task(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/tasks",
        json={
            "message": "Проверь договор и счёт",
            "invoice_id": "inv_101",
            "requested_action": "prepare_payment_draft",
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_failed_safe_stops_cleanly_and_retry_resumes_from_checkpoint(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    monkeypatch,
) -> None:
    original_postflight = SecurityAgent.postflight
    calls = {"count": 0}

    def flaky_postflight(self, *, preflight, accounting, legal, requested_action):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RetryableAgentError("SECURITY_POSTFLIGHT_BUSY", "postflight busy")
        return original_postflight(
            self,
            preflight=preflight,
            accounting=accounting,
            legal=legal,
            requested_action=requested_action,
        )

    monkeypatch.setattr(SecurityAgent, "postflight", flaky_postflight)

    task = await create_draft_task(client)
    # The run stops in a controlled safe state, never in an undefined one.
    assert task["state"] == "failed_safe"
    assert task["result"]["status"] == "failed_safe"
    assert "SECURITY_POSTFLIGHT_BUSY" in task["result"]["warnings"]

    async with create_session_factory(engine)() as session:
        dlq = list(
            await session.scalars(
                select(DeadLetterEntryRecord).where(
                    DeadLetterEntryRecord.task_id == task["task_id"]
                )
            )
        )
        assert len(dlq) == 1
        assert dlq[0].error_code == "SECURITY_POSTFLIGHT_BUSY"
        assert dlq[0].node_id == "security_postflight"
        assert dlq[0].resolved is False
        failed_calls = list(
            await session.scalars(
                select(ProviderCallRecord).where(
                    ProviderCallRecord.task_id == task["task_id"],
                    ProviderCallRecord.status == "failed",
                )
            )
        )
        assert len(failed_calls) == 1
        checkpoints = list(
            await session.scalars(
                select(ExecutionCheckpointRecord).where(
                    ExecutionCheckpointRecord.task_id == task["task_id"]
                )
            )
        )
        # The completed root layer left confirmed checkpoints behind.
        assert {checkpoint.node_id for checkpoint in checkpoints} == {
            "accounting_snapshot",
            "security_preflight",
            "legal_review",
        }

    resumed_response = await client.post(f"/api/v1/tasks/{task['task_id']}/retry")
    assert resumed_response.status_code == 201, resumed_response.text
    resumed = resumed_response.json()
    # The same task resumes (no duplicate run) and reaches the owner decision.
    assert resumed["task_id"] == task["task_id"]
    assert resumed["state"] == "waiting_approval"
    assert resumed["result"]["policy_decision"] == "require_owner_approval"

    trace = (await client.get(f"/api/v1/tasks/{task['task_id']}/trace")).json()
    preflight_steps = [s for s in trace["steps"] if s["node_id"] == "security_preflight"]
    accounting_steps = [s for s in trace["steps"] if s["node_id"] == "accounting_snapshot"]
    # The checkpoint step was not repeated; only the failed node re-executed.
    assert len(preflight_steps) == 1
    assert len(accounting_steps) == 1
    assert {step["attempt"] for step in trace["steps"]} == {1}

    async with create_session_factory(engine)() as session:
        dlq_entries = list(
            await session.scalars(
                select(DeadLetterEntryRecord).where(
                    DeadLetterEntryRecord.task_id == task["task_id"]
                )
            )
        )
        assert len(dlq_entries) == 1  # the historical entry stays for audit


async def test_retry_of_healthy_task_is_rejected(client: httpx.AsyncClient) -> None:
    task = await create_draft_task(client)
    assert task["state"] == "waiting_approval"
    response = await client.post(f"/api/v1/tasks/{task['task_id']}/retry")
    assert response.status_code == 409


async def test_failed_safe_retry_in_queue_mode_publishes_instead_of_running(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    tmp_path,
    monkeypatch,
) -> None:
    """A queued deployment must hand the resumed run to the worker, not the request."""

    original_postflight = SecurityAgent.postflight

    def failing_postflight(self, *, preflight, accounting, legal, requested_action):
        raise RetryableAgentError("SECURITY_POSTFLIGHT_BUSY", "postflight busy")

    monkeypatch.setattr(SecurityAgent, "postflight", failing_postflight)
    task = await create_draft_task(client)
    assert task["state"] == "failed_safe"
    monkeypatch.setattr(SecurityAgent, "postflight", original_postflight)

    async def step_count() -> int:
        async with create_session_factory(engine)() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(TaskStepRecord)
                    .where(TaskStepRecord.task_id == task["task_id"])
                )
                or 0
            )

    steps_before = await step_count()

    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        llm_provider="mock",
        embedding_provider="mock",
        auto_create_schema=False,
        upload_dir=tmp_path / "queue-uploads",
        execution_mode="queue",
    )
    queue_app = create_app(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
    )
    published: list[str] = []
    monkeypatch.setattr(jobs, "publish", lambda task_id: published.append(task_id))
    async with queue_app.router.lifespan_context(queue_app):
        transport = httpx.ASGITransport(app=queue_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as queue_client:
            response = await queue_client.post(f"/api/v1/tasks/{task['task_id']}/retry")
    assert response.status_code == 201, response.text
    resumed = response.json()
    assert resumed["task_id"] == task["task_id"]
    assert resumed["state"] == "queued"
    assert published == [task["task_id"]]

    # The HTTP request did not continue the graph; the worker owns execution.
    assert await step_count() == steps_before
