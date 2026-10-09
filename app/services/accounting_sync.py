import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounting.provider import AccountingProvider
from app.db.tables.accounting_sync import AccountingSyncRecord


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class SyncResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    dataset_version: str
    snapshot_hash: str
    counts: dict[str, int]
    created_at: datetime
    mode: Literal["on_demand_mock_snapshot_receipt"] = "on_demand_mock_snapshot_receipt"
    real_1c_connected: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def sync_snapshot(
    session: AsyncSession,
    provider: AccountingProvider,
    *,
    owner_id: str,
    request_key: str,
    company_id: str = "comp_demo",
) -> SyncResponse:
    query = select(AccountingSyncRecord).where(
        AccountingSyncRecord.company_id == company_id,
        AccountingSyncRecord.owner_id == owner_id,
        AccountingSyncRecord.request_key == request_key,
    )
    existing = await session.scalar(query)
    if existing is not None:
        return SyncResponse.model_validate(existing)
    collections = {
        "counterparties": provider.list_counterparties(),
        "contracts": provider.list_contracts(),
        "invoices": provider.list_invoices(),
        "payments": provider.list_payments(),
        "transactions": provider.list_transactions(),
        "account_balances": provider.list_accounts(),
        "receivables": provider.list_receivables(),
        "receivable_receipts": provider.list_receivable_receipts(),
    }
    snapshot = {
        name: [item.model_dump(mode="json") for item in sorted(rows, key=lambda r: r.id)]
        for name, rows in collections.items()
    }
    journal = provider.accrual_journal()
    payload = {
        "dataset_version": provider.dataset_version,
        "records": snapshot,
        "accrual_journal": journal.model_dump(mode="json") if journal else None,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    record = AccountingSyncRecord(
        company_id=company_id,
        owner_id=owner_id,
        request_key=request_key,
        dataset_version=provider.dataset_version,
        snapshot_hash=digest,
        counts={
            **{name: len(rows) for name, rows in collections.items()},
            "accrual_entries": len(journal.entries) if journal else 0,
        },
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # A concurrent call with the same owner/key is the same operation.
        existing = await session.scalar(query)
        if existing is None:
            raise
        return SyncResponse.model_validate(existing)
    return SyncResponse.model_validate(record)
