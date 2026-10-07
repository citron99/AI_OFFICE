import httpx


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_task_vertical_slice(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/v1/tasks",
        json={"message": "Проверь договор нового подрядчика"},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["state"] == "waiting_input"
    assert payload["category"] == "legal"
    assert payload["result"]["agent"] == "lawyer"
    assert payload["result"]["unresolved_questions"][0].startswith("JURISDICTION_REQUIRED")

    fetched = await client.get(f"/api/v1/tasks/{payload['task_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == payload


async def test_missing_task_returns_domain_error(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/task_missing")
    assert response.status_code == 404
    assert response.json()["code"] == "TASK_NOT_FOUND"
