"""ACC-01: deterministic outputs must equal the golden registry bit-for-bit."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.accounting.mock import Mock1CConnector
from app.accounting.reports import ReportRequest, financial_report
from app.agents.accountant import AccountantAgent
from app.agents.security import SecurityAgent
from app.core.policy import decide

GOLDEN = json.loads((Path(__file__).parent / "golden_values.json").read_text(encoding="utf-8"))
AS_OF = date(2026, 8, 27)
SECURITY = SecurityAgent().execute(["Check invoice"])


def test_dataset_version_is_pinned() -> None:
    assert Mock1CConnector().dataset_version == GOLDEN["dataset_version"]


def test_financial_report_matches_golden() -> None:
    report = financial_report(
        Mock1CConnector(),
        ReportRequest(
            start=date(2026, 7, 1),
            end=date(2026, 7, 31),
            planned_cash_in=Decimal("150000.01"),
            planned_cash_out=Decimal("290000.02"),
        ),
    )
    golden = GOLDEN["financial_report"]
    assert str(report.current.incoming) == golden["cash_in"]
    assert str(report.current.outgoing) == golden["cash_out"]
    assert str(report.current.net) == golden["net"]
    assert str(report.total_bank_balance) == golden["total_bank_balance"]
    assert str(report.total_receivable) == golden["total_receivable"]
    assert len(report.payables) == golden["payables_count"]
    assert {k: str(v) for k, v in sorted(report.receivable_aging.items())} == golden[
        "receivable_aging"
    ]
    assert {k: str(v) for k, v in sorted(report.aging.items())} == golden["aging"]
    assert str(report.plan_fact.incoming_variance) == golden["plan_fact"]["incoming_variance"]
    assert str(report.plan_fact.outgoing_variance) == golden["plan_fact"]["outgoing_variance"]


def test_invoice_results_match_golden() -> None:
    provider = Mock1CConnector()
    for invoice_id, expected in GOLDEN["invoices"].items():
        result = AccountantAgent(provider).execute(invoice_id=invoice_id, as_of=AS_OF)
        assert str(result.outstanding) == expected["outstanding"], invoice_id
        assert sorted({f.code for f in result.findings}) == expected["findings"], invoice_id
        status = result.counterparty.relationship_status if result.counterparty else None
        assert status == expected["counterparty_status"], invoice_id


def test_policy_matrix_matches_golden() -> None:
    base = AccountantAgent(Mock1CConnector()).execute(invoice_id="inv_100", as_of=AS_OF)
    for label, expected in GOLDEN["policy_matrix"].items():
        # Labels encode amount and status: new_100000_00 / est_200000_01.
        kind, amount = label.split("_", 1)
        status = "new" if kind == "new" else "established"
        counterparty = base.counterparty.model_copy(update={"relationship_status": status})
        prepared = base.model_copy(
            update={
                "outstanding": Decimal(amount.replace("_", ".")),
                "findings": [],
                "counterparty": counterparty,
            }
        )
        decision, reasons = decide(
            action="prepare_payment_draft",
            accounting=prepared,
            legal=None,
            security=SECURITY,
        )
        assert decision.value == expected["decision"], label
        assert reasons == expected["reasons"], label
