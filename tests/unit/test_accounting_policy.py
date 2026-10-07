from datetime import date
from decimal import Decimal

import pytest

from app.accounting.mock import Mock1CConnector
from app.agents.accountant import AccountantAgent
from app.agents.security import SecurityAgent
from app.core.policy import decide
from app.core.security import redact
from app.models.enums import AgentType, PolicyDecision
from app.models.legal import LegalResult


def test_snapshot_counts_and_exact_cash_flow() -> None:
    provider = Mock1CConnector()
    assert [
        len(provider.counterparties()),
        len(provider.contracts()),
        len(provider.invoices()),
        len(provider.payments()),
        len(provider.transactions()),
        len(provider.account_balances()),
        len(provider.receivables()),
    ] == [30, 20, 102, 100, 300, 2, 10]
    result = AccountantAgent(provider).execute(invoice_id=None, as_of=date(2026, 8, 27))
    assert result.cash_in == Decimal("151500")
    assert result.cash_out == Decimal("300000")
    assert result.net_cash_flow == Decimal("-148500")
    assert result.invoice_count == 102


@pytest.mark.parametrize(
    "invoice,code",
    [
        ("inv_002", "DUPLICATE_INVOICE"),
        ("inv_003", "TAX_MISMATCH"),
        ("inv_004", "BANK_DETAILS_CHANGED"),
        ("inv_005", "CONTRACT_MISSING"),
        ("inv_006", "CONTRACT_LIMIT"),
        ("inv_007", "OVERDUE"),
    ],
)
def test_synthetic_anomalies(invoice: str, code: str) -> None:
    result = AccountantAgent(Mock1CConnector()).execute(invoice_id=invoice, as_of=date(2026, 8, 27))
    assert code in {f.code for f in result.findings}


def test_policy_matrix_by_tz_section_7_2() -> None:
    accounting = AccountantAgent(Mock1CConnector()).execute(
        invoice_id="inv_100",
        as_of=date(2026, 8, 27),
    )
    assert accounting.outstanding == Decimal("1331.00")
    assert not accounting.findings
    security = SecurityAgent().execute(["Check invoice"])
    # Within the established-counterparty limit a synthetic draft is allowed.
    decision, reasons = decide(
        action="prepare_payment_draft", accounting=accounting, legal=None, security=security
    )
    assert decision == PolicyDecision.ALLOW_DRAFT
    assert "SYNTHETIC_DRAFT_ONLY" in reasons
    assert "REAL_PAYMENT_ALWAYS_MANUAL" in reasons
    # A real payment is never executed by agents, at any amount.
    assert (
        decide(action="real_payment", accounting=accounting, legal=None, security=security)[0]
        == PolicyDecision.OWNER_ONLY_OUTSIDE_AGENT
    )
    assert (
        decide(action="analyze", accounting=accounting, legal=None, security=security)[0]
        == PolicyDecision.ALLOW_READ
    )
    assert (
        decide(action="unknown_action", accounting=accounting, legal=None, security=security)[0]
        == PolicyDecision.DENY
    )
    secret = "password=never-store-this"
    security = SecurityAgent().execute([secret])
    assert "never-store-this" not in security.model_dump_json()
    assert "never-store-this" not in redact(secret)
    decision, reasons = decide(
        action="prepare_payment_draft", accounting=accounting, legal=None, security=security
    )
    assert decision == PolicyDecision.DENY
    assert "SENSITIVE_DATA_DETECTED" in reasons


def test_counterparty_limits_are_versioned_by_relationship_status() -> None:
    provider = Mock1CConnector()
    security = SecurityAgent().execute(["Check invoice"])
    # A new counterparty one kopeck above 100 000 needs owner approval.
    new_counterparty = AccountantAgent(provider).execute(
        invoice_id="inv_001", as_of=date(2026, 8, 27)
    )
    assert new_counterparty.counterparty
    assert new_counterparty.counterparty.relationship_status == "new"
    new_counterparty = new_counterparty.model_copy(
        update={"outstanding": Decimal("100000.01"), "findings": []}
    )
    decision, reasons = decide(
        action="prepare_payment_draft",
        accounting=new_counterparty,
        legal=None,
        security=security,
    )
    assert decision == PolicyDecision.REQUIRE_OWNER_APPROVAL
    assert reasons[0] == "COUNTERPARTY_LIMIT_EXCEEDED"

    # An established counterparty within 200 000 is still a permitted draft.
    established = AccountantAgent(provider).execute(invoice_id="inv_100", as_of=date(2026, 8, 27))
    assert established.counterparty
    assert established.counterparty.relationship_status == "established"
    established = established.model_copy(update={"outstanding": Decimal("150000"), "findings": []})
    decision, reasons = decide(
        action="prepare_payment_draft",
        accounting=established,
        legal=None,
        security=security,
    )
    assert decision == PolicyDecision.ALLOW_DRAFT
    assert "COUNTERPARTY_LIMIT_EXCEEDED" not in reasons


@pytest.mark.parametrize(
    "outstanding,status,expected",
    [
        (Decimal("100000.00"), "new", PolicyDecision.ALLOW_DRAFT),
        (Decimal("100000.01"), "new", PolicyDecision.REQUIRE_OWNER_APPROVAL),
        (Decimal("200000.00"), "established", PolicyDecision.ALLOW_DRAFT),
        (Decimal("200000.01"), "established", PolicyDecision.REQUIRE_OWNER_APPROVAL),
    ],
)
def test_limit_boundaries_are_inclusive(
    outstanding: Decimal, status: str, expected: PolicyDecision
) -> None:
    accounting = AccountantAgent(Mock1CConnector()).execute(
        invoice_id="inv_100", as_of=date(2026, 8, 27)
    )
    counterparty = accounting.counterparty.model_copy(update={"relationship_status": status})
    accounting = accounting.model_copy(
        update={"outstanding": outstanding, "findings": [], "counterparty": counterparty}
    )
    decision, _ = decide(
        action="prepare_payment_draft",
        accounting=accounting,
        legal=None,
        security=SecurityAgent().execute(["Check invoice"]),
    )
    assert decision == expected


def test_failed_legal_analysis_escalates_but_security_still_denies() -> None:
    accounting = AccountantAgent(Mock1CConnector()).execute(
        invoice_id="inv_100", as_of=date(2026, 8, 27)
    )
    legal = LegalResult(
        agent=AgentType.LAWYER,
        status="analysis_unavailable",
        summary="Legal analysis could not be completed.",
        jurisdiction="LV",
        effective_on=date(2026, 8, 27),
    )
    decision, reasons = decide(
        action="prepare_payment_draft",
        accounting=accounting,
        legal=legal,
        security=SecurityAgent().execute(["Check invoice"]),
    )
    assert decision == PolicyDecision.ESCALATE
    assert "LEGAL_ANALYSIS_FAILED" in reasons
    # A critical security control outranks the within-limit amount.
    blocked = SecurityAgent().execute(["Check invoice"])
    blocked.control_flags.append("BANK_DETAILS_CHANGED")
    decision, reasons = decide(
        action="prepare_payment_draft", accounting=accounting, legal=None, security=blocked
    )
    assert decision == PolicyDecision.DENY
    assert "POSTFLIGHT_BANK_DETAILS_CHANGED" in reasons


def test_security_postflight_uses_structured_controls_without_exposing_values() -> None:
    provider = Mock1CConnector()
    accountant = AccountantAgent(provider).execute(invoice_id="inv_004", as_of=date(2026, 8, 27))
    preflight = SecurityAgent().execute(["Check invoice"])
    postflight = SecurityAgent().postflight(
        preflight=preflight,
        accounting=accountant,
        legal=None,
        requested_action="prepare_payment_draft",
    )
    assert "BANK_DETAILS_CHANGED" in postflight.control_flags
    assert "COUNTERPARTY_BLOCKED" in postflight.control_flags
    assert postflight.status == "security_postflight_report"
    assert accountant.counterparty is not None
    assert accountant.counterparty.bank_fingerprint not in postflight.model_dump_json()


def test_security_postflight_accepts_successful_retrieval_only_legal_result() -> None:
    legal = LegalResult(
        agent=AgentType.LAWYER,
        status="retrieval_only",
        summary="Sources were retrieved for specialist review.",
        jurisdiction="LV",
        effective_on=date(2026, 8, 27),
    )
    postflight = SecurityAgent().postflight(
        preflight=SecurityAgent().execute(["Review invoice"]),
        accounting=None,
        legal=legal,
        requested_action="prepare_payment_draft",
    )
    assert "LEGAL_RESULT_UNAVAILABLE" not in postflight.control_flags
