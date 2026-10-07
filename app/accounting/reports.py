from datetime import date, timedelta
from decimal import Decimal

from app.accounting.provider import AccountingProvider
from app.models.accounting import AccountBalance, ReceivableReceipt
from app.models.finance import (
    CashPeriod,
    FinanceReport,
    Payable,
    PlanFact,
    ProfitAndLoss,
    ProfitPeriod,
    ReceivablePosition,
    ReportRequest,
)

ZERO = Decimal("0.00")


def profit_report(provider: AccountingProvider, request: ReportRequest) -> ProfitAndLoss | None:
    journal = provider.accrual_journal()
    if journal is None:
        return None

    def period(start: date, end: date) -> ProfitPeriod | None:
        if start < journal.coverage_start or end > journal.coverage_end:
            return None  # Missing coverage is not zero profit.
        entries = [e for e in journal.entries if start <= e.recognized_on <= end]

        def total(category: str) -> Decimal:
            return sum(
                (
                    (-e.amount if e.reversal else e.amount)
                    for e in entries
                    if e.category == category
                ),
                ZERO,
            )

        revenue, cost = total("revenue"), total("cost_of_sales")
        operating, depreciation = total("operating_expense"), total("depreciation")
        return ProfitPeriod(
            start=start,
            end=end,
            revenue=revenue,
            cost_of_sales=cost,
            gross_profit=revenue - cost,
            operating_expense=operating,
            depreciation=depreciation,
            operating_profit=revenue - cost - operating - depreciation,
            entries=entries,
        )

    current = period(request.start, request.end)
    previous = period(
        request.start - timedelta(days=(request.end - request.start).days + 1),
        request.start - timedelta(days=1),
    )
    warnings = [
        "SYNTHETIC_ACCRUAL_REGISTER: not a statutory double-entry ledger.",
        "OPERATING_PROFIT_ONLY: financing and income taxes absent; not net profit.",
        "NO_CASH_RECONCILIATION: accrual and cash fixtures are independent.",
    ]
    if current is None or previous is None:
        warnings.append("INCOMPLETE_PERIOD_COVERAGE: uncovered periods are null, not zero.")
    return ProfitAndLoss(
        journal_version=journal.version,
        coverage_start=journal.coverage_start,
        coverage_end=journal.coverage_end,
        current=current,
        previous=previous,
        operating_profit_change=current.operating_profit - previous.operating_profit
        if current and previous
        else None,
        warnings=warnings,
    )


def financial_report(provider: AccountingProvider, request: ReportRequest) -> FinanceReport:
    def cash(start: date, end: date) -> CashPeriod:
        rows = [t for t in provider.list_transactions() if start <= t.booked_on <= end]
        incoming = sum((t.amount for t in rows if t.direction == "income"), ZERO)
        outgoing = sum((t.amount for t in rows if t.direction == "expense"), ZERO)
        return CashPeriod(
            start=start,
            end=end,
            incoming=incoming,
            outgoing=outgoing,
            net=incoming - outgoing,
            transaction_ids=[t.id for t in rows],
        )

    days = (request.end - request.start).days + 1
    current = cash(request.start, request.end)
    previous = cash(request.start - timedelta(days=days), request.start - timedelta(days=1))
    payments = [p for p in provider.list_payments() if p.paid_on <= request.end]
    payables = []
    aging = dict.fromkeys(["not_due", "1_30", "31_60", "61_90", "over_90"], ZERO)
    for invoice in provider.list_invoices():
        if invoice.issued_on > request.end:
            continue
        related = [p for p in payments if p.invoice_id == invoice.id]
        paid = sum((p.amount for p in related), ZERO)
        outstanding = max(ZERO, invoice.gross - paid)
        overdue = max(0, (request.end - invoice.due_on).days)
        bucket = (
            "not_due"
            if overdue == 0
            else "1_30"
            if overdue <= 30
            else "31_60"
            if overdue <= 60
            else "61_90"
            if overdue <= 90
            else "over_90"
        )
        aging[bucket] += outstanding
        payables.append(
            Payable(
                invoice_id=invoice.id,
                counterparty_id=invoice.counterparty_id,
                due_on=invoice.due_on,
                gross=invoice.gross,
                paid=paid,
                outstanding=outstanding,
                overpayment=max(ZERO, paid - invoice.gross),
                days_overdue=overdue,
                payment_ids=[p.id for p in related],
            )
        )
    latest: dict[str, AccountBalance] = {}
    seen: set[tuple[str, date]] = set()
    for balance in provider.list_accounts():
        identity = (balance.account_id, balance.as_of)
        if identity in seen:
            raise ValueError("Duplicate account snapshot date")
        seen.add(identity)
        if balance.as_of <= request.end and (
            balance.account_id not in latest or balance.as_of > latest[balance.account_id].as_of
        ):
            latest[balance.account_id] = balance
    balances = [latest[key] for key in sorted(latest)]
    dates = {row.as_of for row in balances}
    # No common date is claimed for a mixed-age set of snapshots.
    balances_as_of = next(iter(dates)) if len(dates) == 1 else None
    account_balance_dates = {row.account_id: row.as_of for row in balances}
    receivables = []
    debts = {row.id: row for row in provider.list_receivables()}
    receipts_all = provider.list_receivable_receipts()
    if len({receipt.id for receipt in receipts_all}) != len(receipts_all):
        raise ValueError("Duplicate receivable receipt ID")
    for receipt in receipts_all:
        debt = debts.get(receipt.receivable_id)
        if (
            debt is None
            or receipt.received_on < debt.issued_on
            or receipt.currency != debt.currency
        ):
            raise ValueError("Invalid receivable receipt reference, date or currency")
    receipts_by_receivable: dict[str, list[ReceivableReceipt]] = {}
    for receipt in receipts_all:
        if receipt.received_on <= request.end:
            receipts_by_receivable.setdefault(receipt.receivable_id, []).append(receipt)
    receivable_aging = dict.fromkeys(["not_due", "1_30", "31_60", "61_90", "over_90"], ZERO)
    for receivable in provider.list_receivables():
        if receivable.issued_on > request.end:
            continue
        receipts = receipts_by_receivable.get(receivable.id, [])
        received = sum((receipt.amount for receipt in receipts), ZERO)
        outstanding = max(ZERO, receivable.gross - received)
        overdue = max(0, (request.end - receivable.due_on).days)
        bucket = (
            "not_due"
            if overdue == 0
            else "1_30"
            if overdue <= 30
            else "31_60"
            if overdue <= 60
            else "61_90"
            if overdue <= 90
            else "over_90"
        )
        receivable_aging[bucket] += outstanding
        receivables.append(
            ReceivablePosition(
                receivable_id=receivable.id,
                counterparty_id=receivable.counterparty_id,
                due_on=receivable.due_on,
                gross=receivable.gross,
                received=received,
                receipt_ids=[receipt.id for receipt in receipts],
                overpayment=max(ZERO, received - receivable.gross),
                outstanding=outstanding,
                days_overdue=overdue,
            )
        )
    plan = None
    if request.planned_cash_in is not None and request.planned_cash_out is not None:
        plan = PlanFact(
            planned_incoming=request.planned_cash_in,
            planned_outgoing=request.planned_cash_out,
            incoming_variance=current.incoming - request.planned_cash_in,
            outgoing_variance=current.outgoing - request.planned_cash_out,
            net_variance=current.net - (request.planned_cash_in - request.planned_cash_out),
        )
    return FinanceReport(
        dataset_version=provider.dataset_version,
        current=current,
        previous=previous,
        net_change=current.net - previous.net,
        plan_fact=plan,
        payables_as_of=request.end,
        payables=payables,
        aging=aging,
        total_outstanding=sum(aging.values(), ZERO),
        total_overpayment=sum((p.overpayment for p in payables), ZERO),
        balances_as_of=balances_as_of,
        account_balance_dates=account_balance_dates,
        account_balances=balances,
        total_bank_balance=sum((row.amount for row in balances), ZERO) if balances else None,
        receivables_as_of=request.end,
        receivables=receivables,
        receivable_aging=receivable_aging,
        total_receivable=sum(receivable_aging.values(), ZERO),
        profit_and_loss=profit_report(provider, request),
    )
