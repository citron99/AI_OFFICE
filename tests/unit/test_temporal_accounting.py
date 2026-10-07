from datetime import date
from decimal import Decimal

import pytest

from app.accounting.mock import Mock1CConnector
from app.accounting.reports import financial_report
from app.models.finance import ReportRequest


def report(provider, day):
    return financial_report(provider, ReportRequest(start=day, end=day))


def test_receipts_respect_date_inclusive_and_report_start_does_not_erase_history():
    provider = Mock1CConnector()
    before = report(provider, date(2026, 7, 19))
    on_date = report(provider, date(2026, 7, 20))
    later = report(provider, date(2026, 8, 1))
    assert before.total_receivable == Decimal("1625000")
    assert all(row.received == 0 and not row.receipt_ids for row in before.receivables)
    assert on_date.total_receivable == later.total_receivable == Decimal("1425000")
    assert sum(len(row.receipt_ids) for row in on_date.receivables) == 7


def test_latest_balance_is_selected_per_account_not_global_date():
    provider = Mock1CConnector()
    original, reserve = provider.account_balances()
    newer = original.model_copy(
        update={
            "id": "newer",
            "as_of": date(2026, 8, 10),
            "amount": Decimal("100"),
        }
    )
    provider._account_balances = (newer, reserve, original)
    before = report(provider, date(2026, 7, 30))
    assert before.total_bank_balance is None
    assert before.account_balances == []
    july = report(provider, date(2026, 7, 31))
    assert july.total_bank_balance == Decimal("3200000")
    august = report(provider, date(2026, 8, 10))
    assert august.total_bank_balance == Decimal("750100")
    assert august.balances_as_of is None
    assert {row.id for row in august.account_balances} == {
        "newer",
        reserve.id,
    }
    assert august.account_balance_dates == {
        "bank_operating": date(2026, 8, 10),
        "bank_reserve": date(2026, 7, 31),
    }


def test_duplicate_snapshot_and_receipt_are_rejected():
    provider = Mock1CConnector()
    provider._account_balances = (*provider.account_balances(), provider.account_balances()[0])
    with pytest.raises(ValueError, match="Duplicate account"):
        report(provider, date(2026, 7, 31))
    provider = Mock1CConnector()
    provider._receivable_receipts = (
        *provider.receivable_receipts(),
        provider.receivable_receipts()[0],
    )
    with pytest.raises(ValueError, match="Duplicate receivable"):
        report(provider, date(2026, 7, 31))


def test_overpayment_is_separate_and_invalid_receipt_is_rejected():
    provider = Mock1CConnector()
    receipt = provider.receivable_receipts()[0]
    provider._receivable_receipts = (receipt.model_copy(update={"amount": Decimal("100000")}),)
    position = report(provider, date(2026, 7, 31)).receivables[0]
    assert position.outstanding == 0
    assert position.overpayment == Decimal("5000")
    provider._receivable_receipts = (receipt.model_copy(update={"received_on": date(2026, 1, 1)}),)
    with pytest.raises(ValueError, match="Invalid receivable"):
        report(provider, date(2026, 7, 31))
