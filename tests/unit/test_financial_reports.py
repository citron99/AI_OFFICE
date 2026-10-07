from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.accounting.mock import Mock1CConnector
from app.accounting.reports import financial_report
from app.models.accounting import Payment
from app.models.finance import ReportRequest


def test_cash_totals_comparison_and_plan_are_exact():
    provider = Mock1CConnector()
    report = financial_report(
        provider,
        ReportRequest(
            start=date(2026, 7, 1),
            end=date(2026, 7, 31),
            planned_cash_in=Decimal("150000.01"),
            planned_cash_out=Decimal("290000.02"),
        ),
    )
    assert report.currency == "RUB"
    assert provider.dataset_version == "synthetic-accounting-rub-v7"
    assert {row.currency for row in provider.contracts()} == {"RUB"}
    assert {row.currency for row in provider.invoices()} == {"RUB"}
    assert {row.currency for row in provider.payments()} == {"RUB"}
    assert {row.currency for row in provider.transactions()} == {"RUB"}
    assert {row.currency for row in provider.account_balances()} == {"RUB"}
    assert {row.currency for row in provider.receivables()} == {"RUB"}
    assert {row.currency for row in provider.accrual_journal().entries} == {"RUB"}
    assert report.current.incoming == Decimal("151500.00")
    assert report.current.outgoing == Decimal("300000.00")
    assert report.current.net == Decimal("-148500.00")
    assert len(report.current.transaction_ids) == 300
    assert report.previous.start == date(2026, 5, 31)
    assert report.previous.end == date(2026, 6, 30)
    assert report.previous.net == 0
    assert report.net_change == report.current.net
    assert report.plan_fact.incoming_variance == Decimal("1499.99")
    assert report.plan_fact.outgoing_variance == Decimal("9999.98")
    assert report.plan_fact.net_variance == Decimal("-8499.99")
    assert report.profit_and_loss.current.operating_profit == Decimal("55000.00")
    assert sum(report.aging.values()) == sum(p.outstanding for p in report.payables)
    assert report.balances_as_of == date(2026, 7, 31)
    assert report.total_bank_balance == Decimal("3200000.00")
    assert report.total_receivable == Decimal("1425000.00")
    assert sum(report.receivable_aging.values()) == sum(
        position.outstanding for position in report.receivables
    )


@pytest.mark.parametrize(
    "days,bucket",
    [
        (0, "not_due"),
        (1, "1_30"),
        (30, "1_30"),
        (31, "31_60"),
        (60, "31_60"),
        (61, "61_90"),
        (90, "61_90"),
        (91, "over_90"),
    ],
)
def test_aging_boundaries(days, bucket):
    provider = Mock1CConnector()
    provider._invoices = (provider.invoices()[0],)
    provider._payments = ()
    end = date(2026, 7, 31) + timedelta(days=days)
    report = financial_report(provider, ReportRequest(start=end, end=end))
    assert report.aging[bucket] == provider.invoices()[0].gross
    assert sum(v for k, v in report.aging.items() if k != bucket) == 0


def test_payables_use_all_history_not_only_report_window_and_ignore_future():
    provider = Mock1CConnector()
    report = financial_report(provider, ReportRequest(start=date(2026, 8, 1), end=date(2026, 8, 2)))
    assert report.current.incoming == 0
    assert report.payables[0].paid > 0  # July payments still settle the liability.
    before = financial_report(
        provider, ReportRequest(start=date(2026, 6, 1), end=date(2026, 6, 30))
    )
    assert before.payables == []
    assert before.total_outstanding == 0
    july = financial_report(provider, ReportRequest(start=date(2026, 7, 1), end=date(2026, 7, 19)))
    assert all(p.paid == 0 for p in july.payables)


def test_overpayment_is_not_netted_against_other_supplier_debt():
    provider = Mock1CConnector()
    provider._payments = (
        Payment(
            id="overpaid",
            invoice_id="inv_001",
            amount=Decimal("1000"),
            paid_on=date(2026, 7, 1),
        ),
    )
    report = financial_report(
        provider, ReportRequest(start=date(2026, 7, 1), end=date(2026, 7, 31))
    )
    first = report.payables[0]
    assert first.outstanding == 0
    assert first.overpayment == Decimal("866.90")
    assert report.total_overpayment == first.overpayment
    assert report.total_outstanding == sum(i.gross for i in provider.invoices()[1:])


@pytest.mark.parametrize(
    "changes",
    [
        {"end": "2026-06-30"},
        {"end": "2028-07-01"},
        {"planned_cash_in": "1"},
        {"planned_cash_in": "-1", "planned_cash_out": "2"},
        {"planned_cash_in": "1.001", "planned_cash_out": "2"},
        {"start": "0001-01-01", "end": "0001-01-01"},
    ],
)
def test_invalid_report_request(changes):
    with pytest.raises(ValidationError):
        ReportRequest.model_validate({"start": "2026-07-01", "end": "2026-07-31", **changes})
