from decimal import Decimal

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.accounting.mock import Mock1CConnector
from app.db.session import create_session_factory
from app.services.accounting_sync import sync_snapshot


async def test_snapshot_receipt_is_idempotent_and_persisted(client: httpx.AsyncClient):
    first = await client.post("/api/v1/accounting/sync", json={"request_key": "probe-1"})
    assert first.status_code == 200, first.text
    second = await client.post("/api/v1/accounting/sync", json={"request_key": "probe-1"})
    assert first.json() == second.json()
    third = await client.post("/api/v1/accounting/sync", json={"request_key": "probe-2"})
    assert third.json()["id"] != first.json()["id"]
    assert third.json()["snapshot_hash"] == first.json()["snapshot_hash"]
    assert first.json()["counts"]["accrual_entries"] == 8
    assert first.json()["counts"]["account_balances"] == 2
    assert first.json()["counts"]["receivables"] == 10
    assert first.json()["real_1c_connected"] is False
    assert len((await client.get("/api/v1/accounting/sync-runs")).json()) == 2
    assert (
        await client.post("/api/v1/accounting/sync", json={"request_key": "../bad"})
    ).status_code == 422


async def test_hash_covers_values_and_original_receipt_is_stable(engine: AsyncEngine):
    provider = Mock1CConnector()
    async with create_session_factory(engine)() as session:
        original = await sync_snapshot(session, provider, owner_id="owner", request_key="before")
        changed = provider.invoices()[0].model_copy(update={"gross": Decimal("999.00")})
        provider._invoices = (changed, *provider.invoices()[1:])
        repeated = await sync_snapshot(session, provider, owner_id="owner", request_key="before")
        current = await sync_snapshot(session, provider, owner_id="owner", request_key="after")
        assert repeated == original
        assert current.counts == original.counts
        assert current.snapshot_hash != original.snapshot_hash


async def test_same_request_key_different_companies_creates_separate_records(
    engine: AsyncEngine,
):
    provider = Mock1CConnector()
    async with create_session_factory(engine)() as session:
        receipt_a = await sync_snapshot(
            session,
            provider,
            owner_id="multi-tenant-owner",
            request_key="shared-key",
            company_id="comp-a",
        )
        receipt_b = await sync_snapshot(
            session,
            provider,
            owner_id="multi-tenant-owner",
            request_key="shared-key",
            company_id="comp-b",
        )
        assert receipt_a.id != receipt_b.id
        repeat_a = await sync_snapshot(
            session,
            provider,
            owner_id="multi-tenant-owner",
            request_key="shared-key",
            company_id="comp-a",
        )
        assert repeat_a.id == receipt_a.id
