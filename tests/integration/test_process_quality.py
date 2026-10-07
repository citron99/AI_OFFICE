import httpx


async def create_completed_task(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/tasks",
        json={"message": "security check", "requested_agent": "security"},
    )
    assert response.status_code == 201
    return response.json()


async def test_process_quality_reports_review_coverage_and_latency(
    client: httpx.AsyncClient,
) -> None:
    first = await create_completed_task(client)
    await create_completed_task(client)
    preview = (await client.get(f"/api/v1/tasks/{first['task_id']}/result-review")).json()
    reviewed = await client.post(
        f"/api/v1/tasks/{first['task_id']}/result-review",
        json={
            "decision": "accepted",
            "reason": "Quality sample reviewed",
            "result_hash": preview["result_hash"],
        },
    )
    assert reviewed.status_code == 200
    report = (await client.get("/api/v1/processes/quality?days=30")).json()
    assert report["completed_tasks"] == 2
    assert report["reviewed_results"] == 1
    assert report["pending_reviews"] == 1
    assert report["review_rate"] == 0.5
    assert report["decisions"] == {
        "accepted": 1,
        "rework_required": 0,
        "rejected": 0,
    }
    assert report["average_review_seconds"] is not None


async def test_process_quality_excludes_uncompleted_results(client: httpx.AsyncClient) -> None:
    task = (
        await client.post(
            "/api/v1/tasks",
            json={
                "message": "contract payment",
                "invoice_id": "inv_101",
                "requested_action": "prepare_payment_draft",
                "jurisdiction": "LV",
                "effective_on": "2026-08-27",
            },
        )
    ).json()
    assert task["state"] == "waiting_approval"
    report = (await client.get("/api/v1/processes/quality?days=30")).json()
    assert report["completed_tasks"] == 0
    assert report["pending_reviews"] == 0


async def test_process_controls_report_postflight_coverage(client: httpx.AsyncClient) -> None:
    task = await client.post(
        "/api/v1/tasks",
        json={
            "message": "Review an invoice without executing a payment",
            "invoice_id": "inv_100",
            "requested_action": "analyze",
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
    )
    assert task.status_code == 201
    assert task.json()["state"] == "completed"
    controls = (await client.get("/api/v1/processes/controls?days=30")).json()
    assert controls["office_results"] == 1
    assert controls["postflight_completed"] == 1
    assert controls["postflight_coverage"] == 1
    assert controls["policy_decisions"] == {
        "allow_read": 1,
        "allow_draft": 0,
        "require_owner_approval": 0,
        "deny": 0,
        "escalate": 0,
        "owner_only_outside_agent": 0,
    }
    assert controls["control_flags"] == {}
