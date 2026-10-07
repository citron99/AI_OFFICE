import httpx

from app.db.session import create_session_factory
from app.db.tables.tasks import TaskRecord
from app.db.tables.users import UserRecord


async def test_task_graph_exposes_persisted_steps_and_review_gate(
    client: httpx.AsyncClient,
) -> None:
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"message": "security check", "requested_agent": "security"},
        )
    ).json()
    response = await client.get(f"/api/v1/tasks/{task['task_id']}/process-graph")
    assert response.status_code == 200
    graph = response.json()
    assert graph["process_id"] == "office_review"
    assert graph["process_version"] == 3
    assert any(
        node["kind"] == "agent_step" and node["readiness"] == "completed" for node in graph["nodes"]
    )
    review = next(node for node in graph["nodes"] if node["id"] == "result_review")
    assert review["readiness"] == "ready"
    preview = (await client.get(f"/api/v1/tasks/{task['task_id']}/result-review")).json()
    assert (
        await client.post(
            f"/api/v1/tasks/{task['task_id']}/result-review",
            json={
                "decision": "accepted",
                "reason": "Graph evidence reviewed",
                "result_hash": preview["result_hash"],
            },
        )
    ).status_code == 200
    reviewed_graph = (await client.get(f"/api/v1/tasks/{task['task_id']}/process-graph")).json()
    reviewed = next(node for node in reviewed_graph["nodes"] if node["id"] == "result_review")
    assert reviewed["readiness"] == "completed"


async def test_task_graph_is_not_disclosed_across_owners(client: httpx.AsyncClient, engine) -> None:
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"message": "security check", "requested_agent": "security"},
        )
    ).json()
    async with create_session_factory(engine)() as session:
        session.add(
            UserRecord(
                id="another-owner",
                email="graph-owner@example.test",
                display_name="Graph owner",
            )
        )
        await session.flush()
        record = await session.get(TaskRecord, task["task_id"])
        record.user_id = "another-owner"
        await session.commit()
    response = await client.get(f"/api/v1/tasks/{task['task_id']}/process-graph")
    assert response.status_code == 404
