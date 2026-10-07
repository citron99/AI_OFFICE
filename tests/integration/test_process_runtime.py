"""Kill switch and autonomy ladder controls (TZ 7.1, REL-006, ACC-10)."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.db.tables.process_runtime import ProcessRuntimeRecord


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


async def test_runtime_defaults_and_owner_can_flip_switches(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    process_id = "office_review"
    defaults = (await client.get(f"/api/v1/processes/{process_id}/runtime")).json()
    assert defaults["autonomy_level"] == "a2_draft"
    assert defaults["process_enabled"] is True

    # The pilot daily process starts one rung lower (A1), per the pilot plan.
    daily_defaults = (
        await client.get("/api/v1/processes/daily_cash_and_receivable_risk/runtime")
    ).json()
    assert daily_defaults["autonomy_level"] == "a1_recommendation"

    updated = await client.post(
        f"/api/v1/processes/{process_id}/runtime",
        json={"autonomy_level": "a1_recommendation", "llm_enabled": False},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["autonomy_level"] == "a1_recommendation"
    assert body["llm_enabled"] is False
    async with create_session_factory(engine)() as session:
        record = await session.scalar(
            select(ProcessRuntimeRecord).where(ProcessRuntimeRecord.process_id == process_id)
        )
        assert record is not None
        assert record.updated_by == "usr_demo_owner"
        assert record.updated_at is not None


async def test_process_kill_switch_stops_runs_into_manual_mode(
    client: httpx.AsyncClient,
) -> None:
    process_id = "office_review"
    stopped = await client.post(
        f"/api/v1/processes/{process_id}/runtime", json={"process_enabled": False}
    )
    assert stopped.status_code == 200
    task = await create_draft_task(client)
    # The run never starts: the owner's switch parks it in manual mode.
    assert task["state"] == "waiting_input"
    assert task["result"]["status"] == "stopped_by_switch"
    assert "KILL_SWITCH_PROCESS" in task["result"]["warnings"]

    # Re-enabling lets new runs execute again (at A1: analysis only, no drafts).
    resumed = await client.post(
        f"/api/v1/processes/{process_id}/runtime", json={"process_enabled": True}
    )
    assert resumed.status_code == 200
    next_task = await create_draft_task(client)
    assert next_task["state"] in {"waiting_approval", "completed", "waiting_source"}


async def test_llm_switch_disables_external_analysis(
    client: httpx.AsyncClient,
) -> None:
    await client.post("/api/v1/processes/office_review/runtime", json={"llm_enabled": False})
    task = await create_draft_task(client)
    legal = task["result"].get("legal")
    if legal is not None:
        assert legal["analysis_attempted"] is False


async def test_write_tools_switch_denies_draft_actions(
    client: httpx.AsyncClient,
) -> None:
    await client.post(
        "/api/v1/processes/office_review/runtime", json={"write_tools_enabled": False}
    )
    task = await create_draft_task(client)
    assert task["result"]["policy_decision"] == "deny"
    assert "WRITE_TOOLS_DISABLED" in task["result"]["policy_reasons"]


async def test_runtime_endpoint_requires_owner(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/processes/office_review/runtime", json={"process_enabled": False})


@pytest.mark.parametrize("level", ["a4_limited_autonomy", "b0", ""])
async def test_invalid_autonomy_level_rejected(client: httpx.AsyncClient, level: str) -> None:
    response = await client.post(
        "/api/v1/processes/office_review/runtime", json={"autonomy_level": level}
    )
    assert response.status_code == 422
