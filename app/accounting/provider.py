"""Canonical AccountingProvider boundary (TZ V2.1 section 8.2).

Mock and production connectors expose identical behaviour: read-only
collections, a sync watermark, deterministic reconciliation and data
quality, and a draft capability that is disabled by default.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.models.accounting import (
    AccountBalance,
    Contract,
    Counterparty,
    Invoice,
    Payment,
    Receivable,
    ReceivableReceipt,
    Transaction,
)
from app.models.accrual import AccrualJournal


class ProviderHealth(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    detail: str | None = None


class SyncWatermark(BaseModel):
    dataset_version: str
    generated_at: datetime
    source: Literal["mock_synthetic", "1c_production"] = "mock_synthetic"


class SyncOutcome(BaseModel):
    watermark: SyncWatermark
    counts: dict[str, int]


class CounterpartyStatusReport(BaseModel):
    """Deterministic NEW/EXISTING verdict from master data only (TZ 7.2)."""

    counterparty_id: str
    relationship_status: Literal["new", "established", "blocked", "unknown"]
    approved_master_card: bool
    active_contract: bool
    reconciled_operations: int
    blocked: bool


class DataQualityReport(BaseModel):
    dataset_version: str
    invoices_checked: int
    duplicate_invoices: int
    tax_mismatches: int
    bank_fingerprint_mismatches: int
    missing_contracts: int
    completeness: float = Field(ge=0, le=1)


class ReconciliationReport(BaseModel):
    dataset_version: str
    invoiced_total: Decimal
    paid_total: Decimal
    outstanding_total: Decimal
    payments_without_invoice: int
    balanced: bool


class DraftCreateRequest(BaseModel):
    """Payload for the optional draft capability; never posts or pays."""

    model_config = {"extra": "forbid"}

    invoice_id: str
    counterparty_id: str
    amount: Decimal = Field(gt=0)
    currency: Literal["RUB"] = "RUB"
    purpose: str = Field(min_length=1, max_length=500)


class DraftResult(BaseModel):
    draft_id: str
    posted: Literal[False] = False
    payment_executed: Literal[False] = False
    note: str


class DraftCapabilityDisabledError(RuntimeError):
    """create_draft is a separate capability and is disabled by default."""


class AccountingProvider(Protocol):
    """Read-only boundary. No payment/write capability exists in the MVP."""

    dataset_version: str

    def healthcheck(self) -> ProviderHealth: ...
    def get_sync_watermark(self) -> SyncWatermark: ...
    def sync_read_only(self) -> SyncOutcome: ...

    # TZ canonical collection names.
    def list_accounts(self) -> tuple[AccountBalance, ...]: ...
    def list_counterparties(self) -> tuple[Counterparty, ...]: ...
    def list_contracts(self) -> tuple[Contract, ...]: ...
    def list_invoices(self) -> tuple[Invoice, ...]: ...
    def list_payments(self) -> tuple[Payment, ...]: ...
    def list_transactions(self) -> tuple[Transaction, ...]: ...
    def list_receivables(self) -> tuple[Receivable, ...]: ...
    def list_receivable_receipts(self) -> tuple[ReceivableReceipt, ...]: ...
    def accrual_journal(self) -> AccrualJournal | None: ...

    def get_counterparty_status(self, counterparty_id: str) -> CounterpartyStatusReport: ...
    def reconcile_snapshot(self) -> ReconciliationReport: ...
    def calculate_data_quality(self) -> DataQualityReport: ...

    def create_draft(self, request: DraftCreateRequest) -> DraftResult: ...
