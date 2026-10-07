from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256

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


def cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Mock1CConnector:
    """Versioned synthetic snapshot. No network and no real 1C/payment methods."""

    dataset_version = "synthetic-accounting-rub-v7"

    def __init__(self, *, allow_draft_capability: bool = False) -> None:
        self._allow_draft_capability = allow_draft_capability
        # The synthetic snapshot is always fresh: produced at read time.
        self._watermark_generated_at = datetime.now(UTC)
        self._counterparties = tuple(
            Counterparty(
                id=f"cp_{i:03}",
                name=f"SYNTHETIC Supplier {i}",
                bank_fingerprint=f"synthetic-bank-{i:03}",
                relationship_status="blocked"
                if i == 4
                else "new"
                if i in {1, 6}
                else "established",
                first_seen_on=date(2026, 7, 1) if i in {1, 6} else date(2024, 1, 1),
                successful_payment_count=0 if i in {1, 6} else 12,
                last_reviewed_on=date(2026, 7, 1),
                risk_tier="blocked" if i == 4 else "elevated" if i in {1, 6} else "standard",
            )
            for i in range(1, 31)
        )
        # contract_002 carries the large above-limit invoice inv_101; contract_001
        # keeps headroom for a new-counterparty above-limit scenario.
        ceilings = {
            contract_id: Decimal("20000")
            for contract_id in (f"contract_{i:03}" for i in range(1, 21))
        }
        ceilings["contract_001"] = Decimal("200000")
        ceilings["contract_002"] = Decimal("300000")
        self._contracts = tuple(
            Contract(
                id=f"contract_{i:03}",
                counterparty_id=f"cp_{i:03}",
                ceiling=ceilings[f"contract_{i:03}"],
            )
            for i in range(1, 21)
        )
        invoices = []
        for i in range(1, 101):
            cp = (i - 1) % 30 + 1
            net = Decimal(100 + i * 10)
            if i == 6:
                net = Decimal("50000")
            tax = cents(net * Decimal("0.21"))
            invoice = Invoice(
                id=f"inv_{i:03}",
                counterparty_id=f"cp_{cp:03}",
                contract_id=f"contract_{cp:03}" if cp <= 20 else None,
                number=f"SYN-{i:03}",
                issued_on=date(2026, 7, 1),
                due_on=date(2026, 7, 31) if i % 2 else date(2026, 9, 30),
                net=net,
                tax=tax,
                gross=net + tax,
                tax_rate=Decimal("0.21"),
                bank_fingerprint=f"synthetic-bank-{cp:03}",
            )
            changes: dict[str, object] = {}
            if i == 2:
                changes = {
                    "counterparty_id": "cp_001",
                    "contract_id": "contract_001",
                    "number": "SYN-001",
                    "bank_fingerprint": "synthetic-bank-001",
                }
            elif i == 3:
                changes = {"tax": tax + Decimal("1")}
            elif i == 4:
                changes = {"bank_fingerprint": "synthetic-bank-CHANGED"}
            elif i == 5:
                changes = {"contract_id": None}
            invoices.append(Invoice.model_validate({**invoice.model_dump(), **changes}))
        # Above-limit scenarios per TZ E2E-2/E2E-3: an established counterparty
        # over 200 000 RUB and a new counterparty over 100 000 RUB, both with no
        # other blockers, exercising REQUIRE_OWNER_APPROVAL.
        for invoice_id, counterparty_id, contract_id, net in (
            ("inv_101", "cp_002", "contract_002", Decimal("200000")),
            ("inv_102", "cp_001", "contract_001", Decimal("100000")),
        ):
            tax = cents(net * Decimal("0.21"))
            invoices.append(
                Invoice(
                    id=invoice_id,
                    counterparty_id=counterparty_id,
                    contract_id=contract_id,
                    number=f"SYN-{invoice_id.split('_')[1]}",
                    issued_on=date(2026, 7, 1),
                    due_on=date(2026, 9, 30),
                    net=net,
                    tax=tax,
                    gross=net + tax,
                    tax_rate=Decimal("0.21"),
                    bank_fingerprint=f"synthetic-bank-{counterparty_id.split('_')[1]}",
                )
            )
        self._invoices = tuple(invoices)
        self._payments = tuple(
            Payment(
                id=f"pay_{i:03}",
                invoice_id=f"inv_{(i - 1) // 2 + 1:03}",
                amount=cents(self._invoices[(i - 1) // 2].gross / Decimal(4)),
                paid_on=date(2026, 7, 20),
            )
            for i in range(1, 101)
        )
        self._transactions = tuple(
            Transaction(
                id=f"txn_{i:03}",
                booked_on=date(2026, 7, 1) + timedelta(days=(i - 1) % 31),
                direction="income" if i % 3 == 0 else "expense",
                amount=Decimal(i * 10),
            )
            for i in range(1, 301)
        )
        self._account_balances = (
            AccountBalance(
                id="balance_operating_20260731",
                account_id="bank_operating",
                account_name="Основной расчётный счёт",
                as_of=date(2026, 7, 31),
                amount=Decimal("2450000.00"),
            ),
            AccountBalance(
                id="balance_reserve_20260731",
                account_id="bank_reserve",
                account_name="Резервный счёт",
                as_of=date(2026, 7, 31),
                amount=Decimal("750000.00"),
            ),
        )
        self._receivables = tuple(
            Receivable(
                id=f"recv_{i:03}",
                counterparty_id=f"cp_{(i + 19) % 30 + 1:03}",
                issued_on=date(2026, 6, 15) + timedelta(days=i),
                due_on=date(2026, 7, 10) + timedelta(days=i * 5),
                gross=Decimal(80000 + i * 15000),
            )
            for i in range(1, 11)
        )
        self._receivable_receipts = tuple(
            ReceivableReceipt(
                id=f"receipt_{i:03}",
                receivable_id=f"recv_{i:03}",
                received_on=date(2026, 7, 20),
                amount=Decimal(20000 * (i % 3)),
            )
            for i in range(1, 11)
            if i % 3
        )

    def counterparties(self) -> tuple[Counterparty, ...]:
        return self._counterparties

    def contracts(self) -> tuple[Contract, ...]:
        return self._contracts

    def invoices(self) -> tuple[Invoice, ...]:
        return self._invoices

    def payments(self) -> tuple[Payment, ...]:
        return self._payments

    def transactions(self) -> tuple[Transaction, ...]:
        return self._transactions

    def account_balances(self) -> tuple[AccountBalance, ...]:
        return self._account_balances

    def receivables(self) -> tuple[Receivable, ...]:
        return self._receivables

    def receivable_receipts(self) -> tuple[ReceivableReceipt, ...]:
        return self._receivable_receipts

    # --- TZ V2.1 section 8.2 canonical contract ---------------------------
    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(status="ok", detail="Synthetic snapshot available")

    def get_sync_watermark(self) -> SyncWatermark:
        return SyncWatermark(
            dataset_version=self.dataset_version,
            generated_at=self._watermark_generated_at,
            source="mock_synthetic",
        )

    def sync_read_only(self) -> SyncOutcome:
        journal = self.accrual_journal()
        return SyncOutcome(
            watermark=self.get_sync_watermark(),
            counts={
                "counterparties": len(self._counterparties),
                "contracts": len(self._contracts),
                "invoices": len(self._invoices),
                "payments": len(self._payments),
                "transactions": len(self._transactions),
                "account_balances": len(self._account_balances),
                "receivables": len(self._receivables),
                "receivable_receipts": len(self._receivable_receipts),
                "accrual_entries": len(journal.entries) if journal else 0,
            },
        )

    def list_accounts(self) -> tuple[AccountBalance, ...]:
        return self._account_balances

    def list_counterparties(self) -> tuple[Counterparty, ...]:
        return self._counterparties

    def list_contracts(self) -> tuple[Contract, ...]:
        return self._contracts

    def list_invoices(self) -> tuple[Invoice, ...]:
        return self._invoices

    def list_payments(self) -> tuple[Payment, ...]:
        return self._payments

    def list_transactions(self) -> tuple[Transaction, ...]:
        return self._transactions

    def list_receivables(self) -> tuple[Receivable, ...]:
        return self._receivables

    def list_receivable_receipts(self) -> tuple[ReceivableReceipt, ...]:
        return self._receivable_receipts

    def get_counterparty_status(self, counterparty_id: str) -> CounterpartyStatusReport:
        counterparty = next((c for c in self._counterparties if c.id == counterparty_id), None)
        if counterparty is None:
            return CounterpartyStatusReport(
                counterparty_id=counterparty_id,
                relationship_status="unknown",
                approved_master_card=False,
                active_contract=False,
                reconciled_operations=0,
                blocked=False,
            )
        counterparty_invoices = {
            i.id for i in self._invoices if i.counterparty_id == counterparty_id
        }
        reconciled_operations = sum(
            1 for p in self._payments if p.invoice_id in counterparty_invoices
        )
        return CounterpartyStatusReport(
            counterparty_id=counterparty.id,
            relationship_status=counterparty.relationship_status,
            approved_master_card=counterparty.last_reviewed_on is not None,
            active_contract=any(c.counterparty_id == counterparty_id for c in self._contracts),
            reconciled_operations=reconciled_operations,
            blocked=counterparty.risk_tier == "blocked",
        )

    def reconcile_snapshot(self) -> ReconciliationReport:
        paid_by_invoice: dict[str, Decimal] = {}
        unknown_payments = 0
        for payment in self._payments:
            if not any(i.id == payment.invoice_id for i in self._invoices):
                unknown_payments += 1
                continue
            paid_by_invoice[payment.invoice_id] = (
                paid_by_invoice.get(payment.invoice_id, Decimal(0)) + payment.amount
            )
        invoiced_total = sum((i.gross for i in self._invoices), Decimal(0))
        paid_total = sum((p.amount for p in self._payments), Decimal(0))
        outstanding_total = sum(
            (
                max(Decimal(0), i.gross - paid_by_invoice.get(i.id, Decimal(0)))
                for i in self._invoices
            ),
            Decimal(0),
        )
        return ReconciliationReport(
            dataset_version=self.dataset_version,
            invoiced_total=invoiced_total,
            paid_total=paid_total,
            outstanding_total=outstanding_total,
            payments_without_invoice=unknown_payments,
            balanced=unknown_payments == 0 and paid_total <= invoiced_total,
        )

    def calculate_data_quality(self) -> DataQualityReport:
        duplicates = sum(
            1
            for a in self._invoices
            for b in self._invoices
            if a.id < b.id and a.counterparty_id == b.counterparty_id and a.number == b.number
        )
        tax_mismatches = sum(1 for i in self._invoices if i.tax != cents(i.net * i.tax_rate))
        bank_mismatches = 0
        missing_contracts = 0
        for invoice in self._invoices:
            counterparty = next(
                (c for c in self._counterparties if c.id == invoice.counterparty_id), None
            )
            if counterparty is None or counterparty.bank_fingerprint != invoice.bank_fingerprint:
                bank_mismatches += 1
            contract = next((c for c in self._contracts if c.id == invoice.contract_id), None)
            if (
                invoice.contract_id is None
                or contract is None
                or contract.counterparty_id != invoice.counterparty_id
            ):
                missing_contracts += 1
        flagged = duplicates + tax_mismatches + bank_mismatches + missing_contracts
        total = len(self._invoices)
        return DataQualityReport(
            dataset_version=self.dataset_version,
            invoices_checked=total,
            duplicate_invoices=duplicates,
            tax_mismatches=tax_mismatches,
            bank_fingerprint_mismatches=bank_mismatches,
            missing_contracts=missing_contracts,
            completeness=round(1 - flagged / total, 6) if total else 1.0,
        )

    def create_draft(self, request: DraftCreateRequest) -> DraftResult:
        if not self._allow_draft_capability:
            raise DraftCapabilityDisabledError(
                "create_draft capability is disabled; enable it explicitly per deployment"
            )
        invoice = next((i for i in self._invoices if i.id == request.invoice_id), None)
        if invoice is None:
            raise ValueError("Unknown invoice")
        if request.amount > invoice.gross:
            raise ValueError("Draft amount exceeds the invoice total")
        digest = sha256(request.model_dump_json().encode()).hexdigest()[:16]
        return DraftResult(
            draft_id=f"draft_synthetic_{digest}",
            note=(
                "Создан только непроведённый черновик. Документ не проведён, платёж не выполнялся."
            ),
        )

    def accrual_journal(self) -> AccrualJournal:
        # Independent fixture of recognised amounts, NOT derived from bank movements.
        rows = [
            ("2026-06-30", "revenue", "120000", False, "June services accepted"),
            ("2026-06-30", "cost_of_sales", "80000", False, "June delivery costs"),
            ("2026-07-10", "revenue", "200000", False, "July services accepted, not yet paid"),
            ("2026-07-12", "cost_of_sales", "100000", False, "July delivery costs recognised"),
            ("2026-07-20", "operating_expense", "30000", False, "July operating costs"),
            ("2026-07-31", "depreciation", "5000", False, "July non-cash depreciation"),
            ("2026-07-31", "revenue", "10000", True, "July service credit adjustment"),
            ("2026-08-01", "revenue", "15000", False, "August services, not July revenue"),
        ]
        return AccrualJournal(
            version="synthetic-accrual-rub-v2",
            coverage_start=date(2026, 5, 1),
            coverage_end=date(2026, 8, 31),
            entries=tuple(
                AccrualEntry.model_validate(
                    {
                        "id": f"acc_{i:03}",
                        "recognized_on": day,
                        "category": category,
                        "amount": amount,
                        "reversal": reversal,
                        "source_reference": f"SYNTHETIC-ACT-{i:03}",
                        "description": description,
                    }
                )
                for i, (day, category, amount, reversal, description) in enumerate(rows, 1)
            ),
        )
