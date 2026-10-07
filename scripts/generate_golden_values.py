"""Generate the ACC-01 golden values registry from the deterministic dataset.

The registry locks every deterministic financial output the system produces:
report totals, aging buckets, per-invoice accounting results and the policy
matrix on the limit boundaries. Re-run only when the synthetic dataset is
intentionally versioned forward:

    uv run python scripts/generate_golden_values.py
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.accounting.mock import Mock1CConnector
from app.accounting.reports import financial_report
from app.agents.accountant import AccountantAgent
from app.agents.security import SecurityAgent
from app.core.policy import decide
from app.models.finance import ReportRequest

OUT = Path(__file__).resolve().parents[1] / "tests" / "unit" / "golden_values.json"
AS_OF = date(2026, 8, 27)
SECURITY = SecurityAgent().execute(["Check invoice"])


def _accounting(invoice_id: str) -> dict:
    result = AccountantAgent(Mock1CConnector()).execute(invoice_id=invoice_id, as_of=AS_OF)
    return {
        "outstanding": str(result.outstanding),
        "findings": sorted({f.code for f in result.findings}),
        "counterparty_status": result.counterparty.relationship_status
        if result.counterparty
        else None,
    }


def main() -> None:
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
    golden: dict = {
        "dataset_version": provider.dataset_version,
        "financial_report": {
            "cash_in": str(report.current.incoming),
            "cash_out": str(report.current.outgoing),
            "net": str(report.current.net),
            "total_bank_balance": str(report.total_bank_balance),
            "total_receivable": str(report.total_receivable),
            "payables_count": len(report.payables),
            "receivable_aging": {k: str(v) for k, v in sorted(report.receivable_aging.items())},
            "aging": {k: str(v) for k, v in sorted(report.aging.items())},
            "plan_fact": {
                "incoming_variance": str(report.plan_fact.incoming_variance),
                "outgoing_variance": str(report.plan_fact.outgoing_variance),
            },
        },
        "invoices": {
            f"inv_{i:03}": _accounting(f"inv_{i:03}") for i in list(range(1, 11)) + [100, 101]
        },
        "policy_matrix": {},
    }
    base = AccountantAgent(provider).execute(invoice_id="inv_100", as_of=AS_OF)
    for label, outstanding, status in [
        ("new_100000_00", "100000.00", "new"),
        ("new_100000_01", "100000.01", "new"),
        ("est_200000_00", "200000.00", "established"),
        ("est_200000_01", "200000.01", "established"),
    ]:
        counterparty = base.counterparty.model_copy(update={"relationship_status": status})
        prepared = base.model_copy(
            update={
                "outstanding": Decimal(outstanding),
                "findings": [],
                "counterparty": counterparty,
            }
        )
        decision, reasons = decide(
            action="prepare_payment_draft", accounting=prepared, legal=None, security=SECURITY
        )
        golden["policy_matrix"][label] = {"decision": decision.value, "reasons": reasons}

    OUT.write_text(
        json.dumps(golden, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Golden values written: {OUT}")


if __name__ == "__main__":
    main()
