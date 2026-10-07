from datetime import date
from decimal import Decimal

from app.accounting.mock import cents
from app.accounting.provider import AccountingProvider
from app.core.exceptions import FileValidationError
from app.models.accounting import AccountingResult, Invoice
from app.models.agent import Citation, Finding
from app.models.enums import AgentType, RiskLevel


class AccountantAgent:
    def __init__(self, provider: AccountingProvider) -> None:
        self.provider = provider

    def execute(self, *, invoice_id: str | None, as_of: date) -> AccountingResult:
        invoices = [i for i in self.provider.list_invoices() if i.issued_on <= as_of]
        payments = [p for p in self.provider.list_payments() if p.paid_on <= as_of]
        paid: dict[str, Decimal] = {}
        for payment in payments:
            paid[payment.invoice_id] = paid.get(payment.invoice_id, Decimal(0)) + payment.amount
        transactions = [t for t in self.provider.list_transactions() if t.booked_on <= as_of]
        incoming = sum((t.amount for t in transactions if t.direction == "income"), Decimal(0))
        outgoing = sum((t.amount for t in transactions if t.direction == "expense"), Decimal(0))
        result = AccountingResult(
            dataset_version=self.provider.dataset_version,
            agent=AgentType.ACCOUNTANT,
            status="accounting_report",
            checked_on=as_of,
            summary="Детерминированная проверка синтетической бухгалтерии.",
            warnings=[
                "SYNTHETIC_DATA_ONLY: не данные реальной компании.",
                "Cash flow не является P&L. Ставка налога задана fixture, не нормой права.",
            ],
            cash_in=incoming,
            cash_out=outgoing,
            net_cash_flow=incoming - outgoing,
            invoice_count=len(invoices),
            payment_count=len(payments),
            overdue_count=sum(i.due_on < as_of and i.gross > paid.get(i.id, 0) for i in invoices),
        )
        if invoice_id is None:
            result.anomaly_count = self._dataset_anomalies(invoices)
            result.citations = [
                Citation(
                    source_id=self.provider.dataset_version, title="Synthetic accounting snapshot"
                )
            ]
            return result
        invoice = next((i for i in invoices if i.id == invoice_id), None)
        if invoice is None:
            raise FileValidationError("Unknown synthetic invoice or invoice not yet issued")
        result.invoice = invoice
        result.paid = paid.get(invoice.id, Decimal(0))
        result.outstanding = max(Decimal(0), invoice.gross - result.paid)
        result.citations = [Citation(source_id=invoice.id, title=invoice.number)]

        def flag(code: str, title: str, risk: RiskLevel = RiskLevel.HIGH) -> None:
            result.findings.append(
                Finding(
                    code=code,
                    title=title,
                    description=title,
                    risk_level=risk,
                    # Every non-overdue accounting finding blocks a draft (TZ 7.2).
                    blocks_draft=risk is not RiskLevel.MEDIUM,
                    citations=result.citations,
                )
            )

        if invoice.tax != cents(invoice.net * invoice.tax_rate):
            flag("TAX_MISMATCH", "Налог не совпадает с заданной ставкой и базой")
        if invoice.gross != invoice.net + invoice.tax:
            flag("TOTAL_MISMATCH", "Итог не равен базе плюс налог")
        if any(self._duplicate(invoice, other) for other in invoices):
            flag("DUPLICATE_INVOICE", "Повтор номера счёта для того же контрагента")
        cp = next(
            (c for c in self.provider.list_counterparties() if c.id == invoice.counterparty_id),
            None,
        )
        result.counterparty = cp
        if cp is None or cp.bank_fingerprint != invoice.bank_fingerprint:
            flag("BANK_DETAILS_CHANGED", "Реквизиты не совпадают с карточкой контрагента")
        contract = next(
            (c for c in self.provider.list_contracts() if c.id == invoice.contract_id), None
        )
        if contract is None or contract.counterparty_id != invoice.counterparty_id:
            flag("CONTRACT_MISSING", "Нет соответствующего договора")
        elif invoice.gross > contract.ceiling:
            flag("CONTRACT_LIMIT", "Сумма превышает лимит синтетического договора")
        if result.paid > invoice.gross:
            flag("OVERPAYMENT", "Сумма оплат превышает счёт")
        if result.outstanding == 0:
            flag("ALREADY_PAID", "Счёт уже оплачен")
        if invoice.due_on < as_of and result.outstanding:
            flag("OVERDUE", "Срок оплаты прошёл", RiskLevel.MEDIUM)
        return result

    def _dataset_anomalies(self, invoices: list[Invoice]) -> int:
        """Dataset-level anomalies: duplicate numbers and tax-base breaks."""
        seen: set[tuple[str, str]] = set()
        anomalies = 0
        for invoice in invoices:
            if (invoice.counterparty_id, invoice.number) in seen:
                anomalies += 1
            seen.add((invoice.counterparty_id, invoice.number))
            if invoice.tax != cents(invoice.net * invoice.tax_rate):
                anomalies += 1
        return anomalies

    def analyze_receivables(self, *, as_of: date) -> AccountingResult:
        """Receivable aging buckets and top non-payment risks (TZ 6.2).

        Lives in the accountant's domain so the Policy Gate and the digest
        consume structured results instead of recomputing them.
        """

        from app.models.digest import NonpaymentRisk

        buckets = {
            "not_due": Decimal("0"),
            "1_30": Decimal("0"),
            "31_60": Decimal("0"),
            "61_90": Decimal("0"),
            "90_plus": Decimal("0"),
        }
        counterparties = {c.id: c for c in self.provider.list_counterparties()}
        risks: list[NonpaymentRisk] = []
        receivable_total = Decimal("0")
        expected_receipts = Decimal("0")
        receipts_by_receivable: dict[str, Decimal] = {}
        for receipt in self.provider.list_receivable_receipts():
            if receipt.received_on <= as_of:
                receipts_by_receivable[receipt.receivable_id] = (
                    receipts_by_receivable.get(receipt.receivable_id, Decimal("0")) + receipt.amount
                )
        for receivable in self.provider.list_receivables():
            outstanding = max(
                Decimal("0"),
                receivable.gross - receipts_by_receivable.get(receivable.id, Decimal("0")),
            )
            if outstanding <= 0:
                continue
            receivable_total += outstanding
            days_overdue = (as_of - receivable.due_on).days
            if days_overdue <= 0:
                bucket = "not_due"
            elif days_overdue <= 30:
                bucket = "1_30"
            elif days_overdue <= 60:
                bucket = "31_60"
            elif days_overdue <= 90:
                bucket = "61_90"
            else:
                bucket = "90_plus"
            buckets[bucket] += outstanding
            if days_overdue > 0:
                expected_receipts += outstanding
                counterparty = counterparties.get(receivable.counterparty_id)
                risks.append(
                    NonpaymentRisk(
                        counterparty_id=receivable.counterparty_id,
                        counterparty_name=(
                            counterparty.name if counterparty else receivable.counterparty_id
                        ),
                        outstanding=str(outstanding),
                        days_overdue=days_overdue,
                        explanation=f"Просрочка {days_overdue} дн. по требованию {receivable.id}",
                        recommended_action=("Связаться с контрагентом и зафиксировать срок оплаты"),
                    )
                )
        risks.sort(key=lambda r: (-r.days_overdue, r.counterparty_id))
        return AccountingResult(
            dataset_version=self.provider.dataset_version,
            agent=AgentType.ACCOUNTANT,
            status="receivable_risk_report",
            summary="Детерминированный анализ дебиторской задолженности и рисков неплатежей.",
            checked_on=as_of,
            warnings=[
                "SYNTHETIC_DATA_ONLY: не данные реальной компании.",
            ],
            receivable_total=receivable_total,
            expected_receipts=str(expected_receipts),
            receivable_aging={k: str(v) for k, v in sorted(buckets.items())},
            nonpayment_risks=risks[:5],
            citations=[
                Citation(source_id=self.provider.dataset_version, title="Receivables snapshot")
            ],
        )

    @staticmethod
    def _duplicate(invoice: Invoice, other: Invoice) -> bool:
        return (
            invoice.id != other.id
            and invoice.counterparty_id == other.counterparty_id
            and invoice.number == other.number
        )
