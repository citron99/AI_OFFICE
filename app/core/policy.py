from decimal import Decimal

from app.models.accounting import AccountingResult
from app.models.enums import PolicyDecision, RiskLevel
from app.models.legal import LegalResult
from app.models.office import SecurityResult

# TZ V2.1 section 7.2: financial autonomy limits, in rubles.
NEW_COUNTERPARTY_LIMIT = Decimal("100000")
EXISTING_COUNTERPARTY_LIMIT = Decimal("200000")

POLICY_VERSION = "tz-v2.1-policy-v1"

_CRITICAL_ACCOUNTING_CODES = frozenset(
    {
        "DUPLICATE_INVOICE",
        "TAX_MISMATCH",
        "BANK_DETAILS_CHANGED",
        "CONTRACT_MISSING",
    }
)


def _has_critical_accounting_risk(accounting: AccountingResult | None) -> bool:
    if accounting is None:
        return False
    if any(f.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} for f in accounting.findings):
        return True
    return any(f.code in _CRITICAL_ACCOUNTING_CODES for f in accounting.findings)


def decide(
    *,
    action: str,
    accounting: AccountingResult | None,
    legal: LegalResult | None,
    security: SecurityResult,
    write_tools_enabled: bool = True,
    autonomy_allows_write: bool = True,
) -> tuple[PolicyDecision, list[str]]:
    """Deterministic policy matrix. LLM output can never change these outcomes."""
    # Stop-line first (TZ 7.3): a detected secret or forbidden data class denies
    # EVERY action, including read-only analysis - before any ALLOW_* is possible.
    if security.detections:
        return PolicyDecision.DENY, ["SENSITIVE_DATA_DETECTED"]
    if action == "prepare_payment_draft" and not write_tools_enabled:
        # REL-006: write tools are switched off for this process.
        return PolicyDecision.DENY, ["WRITE_TOOLS_DISABLED"]
    if action == "prepare_payment_draft" and not autonomy_allows_write:
        # TZ 7.1: A0 shadow and A1 recommendation never produce drafts; the
        # ladder may only rise on measured quality.
        return PolicyDecision.DENY, ["AUTONOMY_LEVEL_BLOCKS_WRITE"]
    if action == "real_payment":
        # A real bank payment is always manual, outside the agent contour.
        return PolicyDecision.OWNER_ONLY_OUTSIDE_AGENT, [
            "REAL_PAYMENT_IS_MANUAL_OUTSIDE_AGENT_CONTOUR"
        ]
    if action == "analyze":
        return PolicyDecision.ALLOW_READ, ["READ_ONLY_RESULT"]
    if action != "prepare_payment_draft":
        return PolicyDecision.DENY, ["ACTION_NOT_SUPPORTED"]

    deny: list[str] = []
    escalate: list[str] = []
    # Security postflight controls are decisive: a user text or LLM output cannot
    # override a blocked counterparty or changed bank details.
    if "BANK_DETAILS_CHANGED" in security.control_flags:
        deny.append("POSTFLIGHT_BANK_DETAILS_CHANGED")
    if "COUNTERPARTY_BLOCKED" in security.control_flags:
        deny.append("POSTFLIGHT_COUNTERPARTY_BLOCKED")
    if _has_critical_accounting_risk(accounting):
        deny.append("ACCOUNTING_BLOCKER")

    if accounting is None or accounting.invoice is None:
        deny.append("INVOICE_REQUIRED")
    elif accounting.outstanding <= 0:
        deny.append("NO_PAYABLE_BALANCE")
    elif accounting.counterparty is None:
        deny.append("COUNTERPARTY_REQUIRED")
    elif accounting.counterparty.relationship_status == "blocked":
        deny.append("COUNTERPARTY_BLOCKED")

    if legal and legal.status in {"analysis_rejected", "analysis_unavailable", "analysis_blocked"}:
        # Legal clearance failed: escalate to a human instead of pretending assurance.
        escalate.append("LEGAL_ANALYSIS_FAILED")
    if "LEGAL_RESULT_UNAVAILABLE" in security.control_flags:
        escalate.append("POSTFLIGHT_LEGAL_RESULT_UNAVAILABLE")

    if deny:
        return PolicyDecision.DENY, deny

    assert accounting is not None and accounting.invoice is not None
    assert accounting.counterparty is not None
    assert accounting.outstanding > 0
    limit = (
        NEW_COUNTERPARTY_LIMIT
        if accounting.counterparty.relationship_status == "new"
        else EXISTING_COUNTERPARTY_LIMIT
    )
    reasons: list[str] = ["SYNTHETIC_DRAFT_ONLY", "REAL_PAYMENT_ALWAYS_MANUAL"]
    if accounting.outstanding > limit:
        # Above the limit the owner approves before the draft is created.
        reasons.insert(0, "COUNTERPARTY_LIMIT_EXCEEDED")
        decision = PolicyDecision.REQUIRE_OWNER_APPROVAL
    else:
        # Within the limit analysis and a non-posted internal draft are allowed.
        decision = PolicyDecision.ALLOW_DRAFT

    if escalate:
        # Critical legal uncertainty is never downgraded by a within-limit amount.
        return PolicyDecision.ESCALATE, sorted({*escalate, *reasons})
    return decision, reasons
