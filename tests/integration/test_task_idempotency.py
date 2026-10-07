import httpx
import pytest


async def test_replay_and_conflict(client: httpx.AsyncClient) -> None:
    headers = {"Idempotency-Key": "submission-1"}
    payload = {"message": "Hello"}
    first = await client.post("/api/v1/tasks", json=payload, headers=headers)
    replay = await client.post("/api/v1/tasks", json=payload, headers=headers)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    conflict = await client.post("/api/v1/tasks", json={"message": "Different"}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json() == {"code": "IDEMPOTENCY_CONFLICT"}
    fresh = await client.post("/api/v1/tasks", json=payload)
    assert fresh.json()["task_id"] != first.json()["task_id"]


@pytest.mark.parametrize("key", ["", "a b", "a" * 129])
async def test_invalid_key(client: httpx.AsyncClient, key: str) -> None:
    response = await client.post(
        "/api/v1/tasks", json={"message": "Hello"}, headers={"Idempotency-Key": key}
    )
    assert response.status_code == 422
