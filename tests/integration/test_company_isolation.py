"""Company isolation: the security boundary for every domain object (ACC-05)."""

import hashlib
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.tasks import TaskRecord
from app.main import create_app


@pytest.fixture
async def two_company_clients(engine: AsyncEngine, tmp_path: Path):
    """Two owner principals of the SAME user in two different companies."""
    settings = Settings(
        app_env="test",
        auth_mode="api_key",
        upload_dir=tmp_path,
        auth_token_hashes={
            hashlib.sha256(token.encode()).hexdigest(): {
                "user_id": user,
                "role": "owner",
                "company_id": company,
            }
            for token, user, company in [
                ("tok-co1", "owner-shared", "comp_one"),
                ("tok-co2", "owner-shared", "comp_two"),
            ]
        },
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c1,
            httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c2,
        ):
            c1.headers["Authorization"] = "Bearer tok-co1"
            c2.headers["Authorization"] = "Bearer tok-co2"
            yield c1, c2


async def _create_task(client: httpx.AsyncClient, message: str) -> dict:
    response = await client.post("/api/v1/tasks", json={"message": message})
    assert response.status_code == 201, response.text
    return response.json()


async def test_same_user_sees_only_their_company_tasks(
    two_company_clients,
) -> None:
    first, second = two_company_clients
    task_one = await _create_task(first, "company one daily control")
    task_two = await _create_task(second, "company two daily control")

    listed_one = {t["task_id"] for t in (await first.get("/api/v1/tasks")).json()}
    listed_two = {t["task_id"] for t in (await second.get("/api/v1/tasks")).json()}
    assert task_one["task_id"] in listed_one
    assert task_two["task_id"] not in listed_one
    assert task_two["task_id"] in listed_two
    assert task_one["task_id"] not in listed_two

    # Direct reads across the company boundary are 404, not 403.
    assert (await first.get(f"/api/v1/tasks/{task_two['task_id']}")).status_code == 404
    assert (await second.get(f"/api/v1/tasks/{task_one['task_id']}")).status_code == 404
    assert (await first.get(f"/api/v1/tasks/{task_two['task_id']}/trace")).status_code == 404


async def test_result_review_is_company_scoped_for_same_user(two_company_clients) -> None:
    first, second = two_company_clients
    task_one = await _create_task(first, "review company one")
    task_two = await _create_task(second, "review company two")

    assert (
        await first.get(f"/api/v1/tasks/{task_one['task_id']}/result-review")
    ).status_code == 200
    assert (
        await first.get(f"/api/v1/tasks/{task_two['task_id']}/result-review")
    ).status_code == 404
    assert (
        await second.get(f"/api/v1/tasks/{task_one['task_id']}/result-review")
    ).status_code == 404


async def test_metrics_are_company_scoped_for_same_user(two_company_clients) -> None:
    first, second = two_company_clients
    await _create_task(first, "first company task one")
    await _create_task(first, "first company task two")
    await _create_task(second, "second company task")

    first_metrics = await first.get("/api/v1/metrics")
    second_metrics = await second.get("/api/v1/metrics")
    assert first_metrics.status_code == 200
    assert second_metrics.status_code == 200
    assert "ai_office_tasks_total 2" in first_metrics.text
    assert "ai_office_tasks_total 1" in second_metrics.text


async def test_company_boundary_holds_for_cancel_and_approvals(
    two_company_clients,
) -> None:
    first, second = two_company_clients
    task_one = await _create_task(first, "invoice check one")
    # The other company cannot cancel a task it cannot see.
    assert (await second.post(f"/api/v1/tasks/{task_one['task_id']}/cancel")).status_code == 404
    # Activity and approvals feeds never leak the other company's records.
    activity_one = await first.get("/api/v1/activity")
    assert activity_one.status_code == 200
    ids_one = {e["task_id"] for e in activity_one.json()["steps"]}
    assert ids_one == {task_one["task_id"]}


async def test_idempotency_is_company_scoped(two_company_clients) -> None:
    """TZ TASK-002: the same Idempotency-Key in another company is a new task."""
    first, second = two_company_clients
    body = {"message": "same request"}
    headers = {"Idempotency-Key": "shared-key-1"}
    original = await first.post("/api/v1/tasks", json=body, headers=headers)
    assert original.status_code == 201, original.text
    replay = await first.post("/api/v1/tasks", json=body, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["task_id"] == original.json()["task_id"]
    # The other company gets its own task for the same key.
    other = await second.post("/api/v1/tasks", json=body, headers=headers)
    assert other.status_code == 201
    assert other.json()["task_id"] != original.json()["task_id"]


async def test_files_are_company_scoped_for_the_same_user(
    two_company_clients,
) -> None:
    """The reviewer's exact scenario: same user_id, upload in A, read in B."""
    first, second = two_company_clients
    uploaded = await first.post(
        "/api/v1/files",
        files={"file": ("company-a.txt", b"Company A confidential report", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    artifact_id = uploaded.json()["id"]
    # Company B (same user_id!) must not download, list in feeds, or delete.
    assert (await second.get(f"/api/v1/files/{artifact_id}")).status_code == 404
    assert (await second.delete(f"/api/v1/files/{artifact_id}")).status_code == 404
    # And the knowledge registry must not leak the foreign source either.
    sources_two = (await second.get("/api/v1/knowledge/sources")).json()
    assert all(s["id"] != artifact_id for s in sources_two)


async def test_company_scope_covers_daily_graph_and_attachments(
    two_company_clients,
    engine: AsyncEngine,
) -> None:
    first, second = two_company_clients
    daily = await first.post(
        "/api/v1/tasks/daily-cash-and-receivable-risk",
        json={"effective_on": "2026-09-28"},
    )
    assert daily.status_code == 201, daily.text
    task_id = daily.json()["task_id"]
    assert (await first.get(f"/api/v1/tasks/{task_id}/process-graph")).status_code == 200
    assert (await second.get(f"/api/v1/tasks/{task_id}/process-graph")).status_code == 404

    async with create_session_factory(engine)() as session:
        record = await session.get(TaskRecord, task_id)
        assert record is not None
        assert record.company_id == "comp_one"

    uploaded = await first.post(
        "/api/v1/files",
        files={"file": ("company-a.txt", b"Company A contract", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    foreign_attachment = await second.post(
        "/api/v1/tasks",
        json={
            "message": "review foreign attachment",
            "attachment_ids": [uploaded.json()["id"]],
        },
    )
    assert foreign_attachment.status_code == 404


async def test_knowledge_is_company_scoped_for_same_user(two_company_clients) -> None:
    first, second = two_company_clients
    uploaded = await first.post(
        "/api/v1/files",
        files={"file": ("law.txt", b"contract evidence company one", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    source = await first.post(
        "/api/v1/knowledge/sources",
        json={
            "artifact_id": uploaded.json()["id"],
            "title": "Company one source",
            "jurisdiction": "LV",
            "document_type": "contract",
            "authority": "internal",
            "version": "1",
            "effective_from": "2026-01-01",
            "status": "ACTIVE",
            "classification": "INTERNAL",
            "language": "ru",
        },
    )
    assert source.status_code == 201, source.text

    own = await first.post(
        "/api/v1/knowledge/search",
        json={
            "query": "contract evidence",
            "jurisdiction": "LV",
            "effective_on": "2026-09-28",
        },
    )
    foreign = await second.post(
        "/api/v1/knowledge/search",
        json={
            "query": "contract evidence",
            "jurisdiction": "LV",
            "effective_on": "2026-09-28",
        },
    )
    assert own.status_code == 200 and own.json()["hits"]
    assert foreign.status_code == 200 and foreign.json()["hits"] == []
    assert (
        await second.post(f"/api/v1/knowledge/sources/{source.json()['id']}/reindex")
    ).status_code == 404
