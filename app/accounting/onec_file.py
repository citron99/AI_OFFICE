"""OneC file-exchange provider skeleton (D-05, TZ 8.2).

Production path without a network connector: the customer exports the
canonical 1С entities to a versioned directory (CSV, UTF-8 with header) and
this adapter parses them into the same AccountingProvider contract the mock
implements. Contract tests run the full shared suite against both providers,
so identical behavior is enforced, not assumed.

Not configured (no directory or missing files) => explicit runtime errors;
fail-closed, never an empty dataset that looks valid.
"""

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from app.accounting.provider import (
    CounterpartyStatusReport,
    DataQualityReport,
    DraftCapabilityDisabledError,
    DraftCreateRequest,
    DraftResult,
    ProviderHealth,
    ReconciliationReport,
    SyncOutcome,
    SyncWatermark,
)
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
from app.models.accrual import AccrualEntry, AccrualJournal

_FILES = {
    "counterparties": Counterparty,
    "contracts": Contract,
    "invoices": Invoice,
    "payments": Payment,
    "transactions": Transaction,
    "account_balances": AccountBalance,
    "receivables": Receivable,
    "receivable_receipts": ReceivableReceipt,
}


def _parse_row(model: Any, row: dict[str, str]) -> BaseModel:
    from typing import get_args, get_origin, get_type_hints

    typed: dict[str, object] = {}
    hints = get_type_hints(model)
    for key, raw in row.items():
        if key not in hints:
            continue
        if raw == "":
            # Optional fields keep their NULL; required ones are reported missing.
            hint = hints[key]
            if get_origin(hint) is not None and type(None) in get_args(hint):
                typed[key] = None
            continue
        hint = hints[key]
        name = getattr(hint, "__name__", str(hint))
        if name == "Decimal":
            typed[key] = Decimal(raw)
        elif name == "date":
            typed[key] = date.fromisoformat(raw)
        elif name == "datetime":
            typed[key] = datetime.fromisoformat(raw)
        elif name == "int":
            typed[key] = int(raw)
        elif name == "float":
            typed[key] = float(raw)
        else:
            typed[key] = raw
    validated: BaseModel = model.model_validate(typed)
    return validated


def _load_csv(directory: Path, name: str, model: Any) -> tuple[BaseModel, ...]:
    path = directory / f"{name}.csv"
    if not path.is_file():
        raise RuntimeError(f"1C file exchange incomplete: missing {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return tuple(_parse_row(model, row) for row in sorted(rows, key=lambda r: r.get("id", "")))


class OneCFileExchangeProvider:
    """Read-only AccountingProvider over a 1С file export directory."""

    def __init__(
        self,
        *,
        exchange_dir: Path,
        watermark: datetime,
        allow_draft_capability: bool = False,
    ) -> None:
        self.exchange_dir = exchange_dir.resolve()
        self._watermark = watermark
        self._allow_draft = allow_draft_capability
        self._data: dict[str, tuple[BaseModel, ...]] = {
            name: _load_csv(self.exchange_dir, name, model) for name, model in _FILES.items()
        }
        self._journal = self._load_journal()

    dataset_version = "onec-file-exchange"

    def _load_journal(self) -> AccrualJournal | None:
        path = self.exchange_dir / "accrual_journal.csv"
        if not path.is_file():
            return None
        with path.open(encoding="utf-8-sig", newline="") as stream:
            entries = tuple(
                AccrualEntry.model_validate(
                    {k: (v if k not in {"amount"} else Decimal(v)) for k, v in row.items()}
                )
                for row in csv.DictReader(stream)
            )
        if not entries:
            return None
        return AccrualJournal(
            version="onec-file-v1",
            entries=entries,
            coverage_start=min(entry.recognized_on for entry in entries),
            coverage_end=max(entry.recognized_on for entry in entries),
        )

    # --- TZ 8.2 canonical contract ---------------------------------------
    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(status="ok", detail=f"File exchange at {self.exchange_dir}")

    def get_sync_watermark(self) -> SyncWatermark:
        return SyncWatermark(
            dataset_version=self.dataset_version,
            generated_at=self._watermark,
            source="1c_production",
        )

    def sync_read_only(self) -> SyncOutcome:
        counts = {name: len(rows) for name, rows in self._data.items()}
        counts["accrual_entries"] = len(self._journal.entries) if self._journal else 0
        return SyncOutcome(
            watermark=self.get_sync_watermark(),
            counts=counts,
        )

    def list_accounts(self) -> tuple[AccountBalance, ...]:
        return cast("tuple[AccountBalance, ...]", self._data["account_balances"])

    def list_counterparties(self) -> tuple[Counterparty, ...]:
        return cast("tuple[Counterparty, ...]", self._data["counterparties"])

    def list_contracts(self) -> tuple[Contract, ...]:
        return cast("tuple[Contract, ...]", self._data["contracts"])

    def list_invoices(self) -> tuple[Invoice, ...]:
        return cast("tuple[Invoice, ...]", self._data["invoices"])

    def list_payments(self) -> tuple[Payment, ...]:
        return cast("tuple[Payment, ...]", self._data["payments"])

    def list_transactions(self) -> tuple[Transaction, ...]:
        return cast("tuple[Transaction, ...]", self._data["transactions"])

    def list_receivables(self) -> tuple[Receivable, ...]:
        return cast("tuple[Receivable, ...]", self._data["receivables"])

    def list_receivable_receipts(self) -> tuple[ReceivableReceipt, ...]:
        return cast("tuple[ReceivableReceipt, ...]", self._data["receivable_receipts"])

    def accrual_journal(self) -> AccrualJournal | None:
        return self._journal

    def get_counterparty_status(self, counterparty_id: str) -> CounterpartyStatusReport:
        counterparty = next(
            (c for c in self.list_counterparties() if c.id == counterparty_id), None
        )
        if counterparty is None:
            return CounterpartyStatusReport(
                counterparty_id=counterparty_id,
                relationship_status="unknown",
                approved_master_card=False,
                active_contract=False,
                reconciled_operations=0,
                blocked=False,
            )
        invoice_ids = {i.id for i in self.list_invoices() if i.counterparty_id == counterparty_id}
        return CounterpartyStatusReport(
            counterparty_id=counterparty.id,
            relationship_status=counterparty.relationship_status,
            approved_master_card=True,
            active_contract=any(
                c.counterparty_id == counterparty_id for c in self.list_contracts()
            ),
            reconciled_operations=sum(
                1 for p in self.list_payments() if p.invoice_id in invoice_ids
            ),
            blocked=counterparty.risk_tier == "blocked",
        )

    def reconcile_snapshot(self) -> ReconciliationReport:
        invoices = self.list_invoices()
        paid_by_invoice: dict[str, Decimal] = {}
        unknown = 0
        for payment in self.list_payments():
            if not any(i.id == payment.invoice_id for i in invoices):
                unknown += 1
                continue
            paid_by_invoice[payment.invoice_id] = (
                paid_by_invoice.get(payment.invoice_id, Decimal("0")) + payment.amount
            )
        invoiced = sum((i.gross for i in invoices), Decimal("0"))
        paid = sum((p.amount for p in self.list_payments()), Decimal("0"))
        outstanding = sum(
            (
                max(Decimal("0"), i.gross - paid_by_invoice.get(i.id, Decimal("0")))
                for i in invoices
            ),
            Decimal("0"),
        )
        return ReconciliationReport(
            dataset_version=self.dataset_version,
            invoiced_total=invoiced,
            paid_total=paid,
            outstanding_total=outstanding,
            payments_without_invoice=unknown,
            balanced=unknown == 0 and paid <= invoiced,
        )

    def calculate_data_quality(self) -> DataQualityReport:
        invoices = self.list_invoices()
        duplicates = sum(
            1
            for i, a in enumerate(invoices)
            for b in invoices[i + 1 :]
            if a.counterparty_id == b.counterparty_id and a.number == b.number
        )
        tax_mismatches = sum(
            1 for i in invoices if i.tax != (i.net * i.tax_rate).quantize(Decimal("0.01"))
        )
        flagged = duplicates + tax_mismatches
        total = len(invoices)
        return DataQualityReport(
            dataset_version=self.dataset_version,
            invoices_checked=total,
            duplicate_invoices=duplicates,
            tax_mismatches=tax_mismatches,
            bank_fingerprint_mismatches=0,
            missing_contracts=0,
            completeness=round(1 - flagged / total, 6) if total else 1.0,
        )

    def create_draft(self, request: DraftCreateRequest) -> DraftResult:
        if not self._allow_draft:
            raise DraftCapabilityDisabledError(
                "create_draft capability is disabled; enable it explicitly per deployment"
            )
        raise NotImplementedError(
            "1C file exchange is read-only; draft posting requires the write API"
        )
