import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.accounting_sync import AccountingSyncRecord
from app.db.tables.approvals import ApprovalRecord
from app.main import create_app


async def create_draft_task(client: httpx.AsyncClient, invoice: str = "inv_101") -> dict:
    response = await client.post(
        "/api/v1/tasks",
        json={
            "message": "Проверь договор и счёт",
            "invoice_id": invoice,
            "requested_action": "prepare_payment_draft",
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_mixed_review_approval_and_idempotent_draft(client: httpx.AsyncClient) -> None:
    task = await create_draft_task(client)
    assert task["state"] == "waiting_approval"
    assert task["run_budget"]["max_steps"] == 8
    assert task["run_usage"]["steps_started"] == 4
    result = task["result"]
    assert result["accounting"]["outstanding"] == "242000.00"
    assert result["legal"]["status"] == "legal_source_not_found"
    assert result["policy_decision"] == "require_owner_approval"
    assert (await client.get("/api/v1/drafts")).json() == []
    path = f"/api/v1/approvals/{result['approval_id']}/decision"
    first = await client.post(path, json={"decision": "approve"})
    assert first.status_code == 200, first.text
    second = await client.post(path, json={"decision": "approve"})
    assert first.json() == second.json()
    drafts = (await client.get("/api/v1/drafts")).json()
    assert len(drafts) == 1
    assert drafts[0]["payload"]["real_payment_allowed"] is False
    assert (await client.post(path, json={"decision": "reject"})).status_code == 409
    trace = (await client.get(f"/api/v1/tasks/{task['task_id']}/trace")).json()
    assert len(trace["steps"]) == 4
    assert {step["node_id"] for step in trace["steps"]} == {
        "accounting_snapshot",
        "security_preflight",
        "legal_review",
        "security_postflight",
    }
    assert {step["attempt"] for step in trace["steps"]} == {1}
    graph = (await client.get(f"/api/v1/tasks/{task['task_id']}/process-graph")).json()
    nodes = {node["action"]: node for node in graph["nodes"] if node["kind"] == "agent_step"}
    assert nodes["accountant_pilot"]["depends_on"] == []
    assert nodes["security_preflight"]["depends_on"] == []
    assert nodes["lawyer_pilot"]["depends_on"] == [nodes["security_preflight"]["id"]]
    assert set(nodes["security_postflight"]["depends_on"]) == {
        nodes["accountant_pilot"]["id"],
        nodes["security_preflight"]["id"],
        nodes["lawyer_pilot"]["id"],
    }
    assert {e["event"] for e in trace["audit"]} == {
        "approval_requested",
        "office_result",
        "approval_approved",
    }
    activity = (await client.get("/api/v1/activity")).json()
    assert {event["task_id"] for event in activity["audit"]} == {task["task_id"]}
    assert {step["task_id"] for step in activity["steps"]} == {task["task_id"]}


async def test_blocked_invoice_has_no_approval(client: httpx.AsyncClient) -> None:
    task = await create_draft_task(client, "inv_004")
    assert task["result"]["policy_decision"] == "deny"
    assert (await client.get("/api/v1/approvals")).json() == []


async def test_within_limit_draft_is_allowed_without_owner_approval(
    client: httpx.AsyncClient,
) -> None:
    # inv_100: established counterparty, 1331.00 RUB outstanding, no blockers.
    task = await create_draft_task(client, "inv_100")
    assert task["state"] == "completed"
    result = task["result"]
    assert result["policy_decision"] == "allow_draft"
    assert result["status"] == "draft_created_synthetically"
    assert result["requires_approval"] is False
    assert result["approval_id"] is None
    drafts = (await client.get("/api/v1/drafts")).json()
    assert len(drafts) == 1
    assert drafts[0]["approval_id"] is None
    assert drafts[0]["payload"]["auto"] is True
    # The synthetic draft never posts a document or pays.
    assert drafts[0]["payload"]["action"] == "create_mock_payment_draft"


async def test_admin_cannot_decide_business_approvals(engine: AsyncEngine, tmp_path: Path) -> None:
    """APR-006: a technical administrator never approves monetary actions."""
    settings = Settings(
        app_env="test",
        auth_mode="api_key",
        upload_dir=tmp_path,
        auth_token_hashes={
            hashlib.sha256(token.encode()).hexdigest(): {"user_id": user, "role": role}
            for token, user, role in [
                ("test-owner-x", "owner-x", "owner"),
                ("test-admin-x", "owner-x", "admin"),
            ]
        },
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            c.headers["Authorization"] = "Bearer test-owner-x"
            task = await create_draft_task(c)
            assert task["state"] == "waiting_approval"
            path = f"/api/v1/approvals/{task['result']['approval_id']}/decision"
            c.headers["Authorization"] = "Bearer test-admin-x"
            forbidden = await c.post(path, json={"decision": "approve"})
            assert forbidden.status_code == 403
            drafts = (await c.get("/api/v1/drafts")).json()
            assert drafts == []
            c.headers["Authorization"] = "Bearer test-owner-x"
            approved = await c.post(path, json={"decision": "approve"})
            assert approved.status_code == 200
            assert (await c.get("/api/v1/drafts")).json()[0]["approval_id"] is not None


async def test_daily_cash_and_receivable_risk_process_runs_its_parallel_controls(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/tasks/daily-cash-and-receivable-risk",
        json={"effective_on": "2026-08-27"},
    )
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["state"] == "completed"
    assert task["process"]["id"] == "daily_cash_and_receivable_risk"
    assert task["run_usage"]["steps_started"] == 5
    # The accepted result is the DailyOwnerDigest (TZ 6.2), not a bare report:
    digest = task["result"]
    assert digest["mode"] == "daily_owner_digest_v1"
    assert digest["cash_available"] == "3200000.00"
    assert digest["net_cash_flow"] == "-148500"
    assert digest["receivable_total"] == "1425000"
    assert digest["receivable_aging"]["1_30"] == "945000"
    assert digest["top_nonpayment_risks"], "top non-payment risks must be listed"
    first_risk = digest["top_nonpayment_risks"][0]
    assert first_risk["days_overdue"] > 0 and first_risk["recommended_action"]
    assert digest["watermark"].startswith("synthetic-accounting-rub-v7")
    assert digest["anomaly_count"] >= 1
    trace = (await client.get(f"/api/v1/tasks/{task['task_id']}/trace")).json()
    by_node = {step["node_id"]: step for step in trace["steps"]}
    assert by_node["cash_control"]["depends_on"] == [by_node["accounting_snapshot"]["id"]]
    assert by_node["receivable_risk"]["depends_on"] == [by_node["accounting_snapshot"]["id"]]
    assert set(by_node["security_postflight"]["depends_on"]) == {
        by_node["accounting_snapshot"]["id"],
        by_node["cash_control"]["id"],
        by_node["receivable_risk"]["id"],
        by_node["security_preflight"]["id"],
    }


@pytest.mark.parametrize("case", ["expired", "tampered", "cancelled"])
async def test_invalid_approval_never_creates_draft(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    case: str,
) -> None:
    task = await create_draft_task(client)
    approval_id = task["result"]["approval_id"]
    if case == "cancelled":
        path = f"/api/v1/tasks/{task['task_id']}/cancel"
        cancelled = await client.post(path)
        assert cancelled.status_code == 200
        assert cancelled.json()["result"]["requires_approval"] is False
        repeated = await client.post(path)
        assert repeated.json() == cancelled.json()
        approvals = (await client.get("/api/v1/approvals")).json()
        assert approvals[0]["status"] == "cancelled"
        trace = (await client.get(f"/api/v1/tasks/{task['task_id']}/trace")).json()
        assert sum(e["event"] == "approval_cancelled" for e in trace["audit"]) == 1
        assert sum(e["event"] == "task_cancelled" for e in trace["audit"]) == 1
    else:
        async with create_session_factory(engine)() as session:
            record = await session.scalar(
                select(ApprovalRecord).where(ApprovalRecord.id == approval_id)
            )
            assert record
            if case == "expired":
                record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            else:
                record.payload = {**record.payload, "amount": "999"}
            await session.commit()
    response = await client.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}
    )
    assert response.status_code == 409
    assert (await client.get("/api/v1/drafts")).json() == []
    if case == "expired":
        expired = (await client.get(f"/api/v1/tasks/{task['task_id']}")).json()
        assert expired["state"] == "completed"
        assert expired["result"]["status"] == "approval_expired"
        assert expired["result"]["requires_approval"] is False


async def test_auth_isolation_and_read_only_role(engine: AsyncEngine, tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        auth_mode="api_key",
        upload_dir=tmp_path,
        auth_token_hashes={
            hashlib.sha256(token.encode()).hexdigest(): {"user_id": user, "role": role}
            for token, user, role in [
                ("test-owner-a", "owner-a", "owner"),
                ("test-owner-b", "owner-b", "owner"),
                ("test-viewer-a", "owner-a", "auditor"),
            ]
        },
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            assert (await c.get("/api/v1/tasks")).status_code == 401
            assert (
                await c.post(
                    "/api/v1/accounting/financial-report",
                    json={"start": "2026-07-01", "end": "2026-07-31"},
                )
            ).status_code == 401
            c.headers["Authorization"] = "Bearer test-owner-a"
            synced = await c.post("/api/v1/accounting/sync", json={"request_key": "same-key"})
            assert synced.status_code == 200
            task = await create_draft_task(c)
            c.headers["Authorization"] = "Bearer test-owner-b"
            assert (await c.get("/api/v1/accounting/sync-runs")).json() == []
            other = await c.post("/api/v1/accounting/sync", json={"request_key": "same-key"})
            assert other.json()["id"] != synced.json()["id"]
            assert (await c.get(f"/api/v1/tasks/{task['task_id']}")).status_code == 404
            assert (await c.get("/api/v1/activity")).json() == {"audit": [], "steps": []}
            assert (
                await c.post(
                    f"/api/v1/approvals/{task['result']['approval_id']}/decision",
                    json={"decision": "approve"},
                )
            ).status_code == 404
            assert (await c.get("/api/v1/tasks")).json() == []
            c.headers["Authorization"] = "Bearer test-viewer-a"
            assert (
                await c.post("/api/v1/accounting/sync", json={"request_key": "read-only"})
            ).status_code == 403
            assert len((await c.get("/api/v1/accounting/sync-runs")).json()) == 1
            assert (
                await c.post(
                    "/api/v1/accounting/financial-report",
                    json={"start": "2026-07-01", "end": "2026-07-31"},
                )
            ).status_code == 200
            assert (await c.post("/api/v1/tasks", json={"message": "invoice"})).status_code == 403
            assert (await c.get(f"/api/v1/tasks/{task['task_id']}")).status_code == 200


async def test_tenant_queries_exclude_null_company_id(engine: AsyncEngine, tmp_path: Path) -> None:
    """Legacy records with company_id=NULL must not leak into tenant-scoped lists."""
    settings = Settings(
        app_env="test",
        auth_mode="api_key",
        upload_dir=tmp_path,
        auth_token_hashes={
            hashlib.sha256(b"test-tenant-owner").hexdigest(): {
                "user_id": "tenant-owner",
                "role": "owner",
            }
        },
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            c.headers["Authorization"] = "Bearer test-tenant-owner"
            async with create_session_factory(engine)() as session:
                session.add(
                    AccountingSyncRecord(
                        company_id=None,
                        owner_id="tenant-owner",
                        request_key="legacy-sync",
                        dataset_version="v1",
                        snapshot_hash="abc",
                        counts={},
                    )
                )
                await session.commit()
            sync_runs = await c.get("/api/v1/accounting/sync-runs")
            assert sync_runs.json() == []
