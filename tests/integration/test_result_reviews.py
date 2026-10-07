import httpx
from sqlalchemy import func, select

from app.db.session import create_session_factory
from app.db.tables.approvals import AuditRecord, DraftRecord
from app.db.tables.tasks import TaskRecord
from app.db.tables.users import UserRecord


async def test_contract_and_review_do_not_authorize_actions(client: httpx.AsyncClient, engine):
    response = await client.post(
        "/api/v1/tasks",
        json={
            "message": "security check",
            "requested_agent": "security",
        },
    )
    assert response.status_code == 201
    task = response.json()
    assert task["state"] == "completed"
    assert task["process"]["version"] == 3
    assert task["process"]["result_owner_id"] == "usr_demo_owner"
    path = f"/api/v1/tasks/{task['task_id']}/result-review"
    preview = (await client.get(path)).json()
    assert preview["eligible"]
    payload = {"decision": "accepted", "reason": "Проверено", "result_hash": preview["result_hash"]}
    payload = {
        "decision": "accepted",
        "reason": "Review completed",
        "result_hash": preview["result_hash"],
    }
    stale = await client.post(path, json={**payload, "result_hash": "0" * 64})
    assert stale.status_code == 409
    first = await client.post(path, json=payload)
    assert first.status_code == 200, first.text
    assert (await client.post(path, json=payload)).json() == first.json()
    assert (await client.post(path, json={**payload, "decision": "rejected"})).status_code == 409
    async with create_session_factory(engine)() as session:
        assert await session.scalar(select(func.count()).select_from(DraftRecord)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditRecord)
                .where(
                    AuditRecord.event == "result_reviewed",
                )
            )
            == 1
        )
        record = await session.get(TaskRecord, task["task_id"])
        assert record.state == "completed"


async def test_legacy_and_other_owner_cannot_be_reviewed(client, engine):
    created = (
        await client.post(
            "/api/v1/tasks",
            json={
                "message": "security check",
                "requested_agent": "security",
            },
        )
    ).json()
    path = f"/api/v1/tasks/{created['task_id']}/result-review"
    preview = (await client.get(path)).json()
    payload = {
        "decision": "rework_required",
        "reason": "Нужны основания",
        "result_hash": preview["result_hash"],
    }
    payload = {
        "decision": "rework_required",
        "reason": "Evidence required",
        "result_hash": preview["result_hash"],
        "target_node_ids": ["security_preflight"],
    }
    async with create_session_factory(engine)() as session:
        record = await session.get(TaskRecord, created["task_id"])
        record.process_snapshot = None
        await session.commit()
    assert (await client.post(path, json=payload)).status_code == 409
    async with create_session_factory(engine)() as session:
        record = await session.get(TaskRecord, created["task_id"])
        session.add(
            UserRecord(
                id="another-owner",
                email="another-owner@example.test",
                display_name="Another owner",
            )
        )
        await session.flush()
        record.user_id = "another-owner"
        await session.commit()
    assert (await client.get(path)).status_code == 404
    assert (await client.post(path, json=payload)).status_code == 404


async def test_rework_creates_a_linked_run_for_selected_graph_node(client):
    original = (
        await client.post(
            "/api/v1/tasks",
            json={"message": "security check", "requested_agent": "security"},
        )
    ).json()
    review_path = f"/api/v1/tasks/{original['task_id']}/result-review"
    preview = (await client.get(review_path)).json()
    payload = {
        "decision": "rework_required",
        "reason": "Repeat the preflight evidence check",
        "result_hash": preview["result_hash"],
        "target_node_ids": ["security_preflight"],
    }
    response = await client.post(review_path, json=payload)
    assert response.status_code == 200, response.text
    review = response.json()
    assert review["target_node_ids"] == ["security_preflight"]
    assert review["rework_task_id"]
    replay = (await client.post(review_path, json=payload)).json()
    assert replay == review
    child = (await client.get(f"/api/v1/tasks/{review['rework_task_id']}")).json()
    assert child["state"] == "completed"
    assert child["rework_parent_task_id"] == original["task_id"]
    assert child["rework_target_node_ids"] == ["security_preflight"]
    assert child["rework_cycle"] == 1
    trace = (await client.get(f"/api/v1/tasks/{child['task_id']}/trace")).json()
    assert {step["node_id"] for step in trace["steps"]} == {
        "security_preflight",
        "security_postflight",
    }
