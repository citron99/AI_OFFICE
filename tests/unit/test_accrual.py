from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.accounting.mock import Mock1CConnector
from app.accounting.reports import profit_report
from app.models.accrual import AccrualJournal
from app.models.finance import ReportRequest


def test_profit_uses_recognition_and_reversals_not_cash():
    provider = Mock1CConnector()
    provider._transactions = ()
    provider._payments = ()
    report = profit_report(provider, ReportRequest(start=date(2026, 7, 1), end=date(2026, 7, 31)))
    assert report.current.revenue == Decimal("190000")
    assert report.current.gross_profit == Decimal("90000")
    assert report.current.operating_profit == Decimal("55000")
    assert report.previous.operating_profit == Decimal("40000")
    assert report.operating_profit_change == Decimal("15000")
    assert len(report.current.entries) == 5
    assert all(e.source_reference for e in report.current.entries)


def test_uncovered_is_not_zero_and_empty_covered_is_zero():
    provider = Mock1CConnector()
    report = profit_report(provider, ReportRequest(start=date(2026, 9, 1), end=date(2026, 9, 30)))
    assert report.current is None
    assert report.previous is not None
    assert report.operating_profit_change is None
    empty = profit_report(provider, ReportRequest(start=date(2026, 5, 15), end=date(2026, 5, 15)))
    assert empty.current.operating_profit == 0
    assert empty.current.entries == []


def test_one_day_includes_depreciation_and_reversal():
    report = profit_report(
        Mock1CConnector(),
        ReportRequest(
            start=date(2026, 7, 31),
            end=date(2026, 7, 31),
        ),
    )
    assert report.current.operating_profit == Decimal("-15000")
    assert len(report.current.entries) == 2


@pytest.mark.parametrize("case", ["duplicate", "outside", "negative", "subcent"])
def test_invalid_journal_rejected(case):
    data = Mock1CConnector().accrual_journal().model_dump(mode="json")
    if case == "duplicate":
        data["entries"].append(data["entries"][0])
    elif case == "outside":
        data["entries"][0]["recognized_on"] = "2027-01-01"
    elif case == "negative":
        data["entries"][0]["amount"] = "-1"
    else:
        data["entries"][0]["amount"] = "0.001"
    with pytest.raises(ValidationError):
        AccrualJournal.model_validate(data)


def test_absent_journal_is_unavailable():
    class NoJournal(Mock1CConnector):
        def accrual_journal(self):
            return None

    assert (
        profit_report(
            NoJournal(),
            ReportRequest(
                start=date(2026, 7, 1),
                end=date(2026, 7, 31),
            ),
        )
        is None
    )
