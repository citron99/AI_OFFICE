"""Contract tests for the canonical AccountingProvider boundary (TZ 8.2)."""

from decimal import Decimal

import pytest

from app.accounting.mock import Mock1CConnector
from app.accounting.provider import DraftCapabilityDisabledError, DraftCreateRequest


def test_healthcheck_and_watermark_are_deterministic() -> None:
    provider = Mock1CConnector()
    health = provider.healthcheck()
    assert health.status == "ok"
    watermark = provider.get_sync_watermark()
    assert watermark.dataset_version == provider.dataset_version
    # The synthetic snapshot is always fresh (produced at read time).
    from datetime import UTC, datetime, timedelta

    assert watermark.generated_at >= datetime.now(UTC) - timedelta(minutes=1)
    assert watermark.source == "mock_synthetic"


def test_sync_read_only_reports_full_collection_counts() -> None:
    outcome = Mock1CConnector().sync_read_only()
    assert outcome.watermark.dataset_version == "synthetic-accounting-rub-v7"
    assert outcome.counts == {
        "counterparties": 30,
        "contracts": 20,
        "invoices": 102,
        "payments": 100,
        "transactions": 300,
        "account_balances": 2,
        "receivables": 10,
        "receivable_receipts": 7,
        "accrual_entries": 8,
    }


def test_counterparty_status_is_deterministic_from_master_data() -> None:
    provider = Mock1CConnector()
    new_cp = provider.get_counterparty_status("cp_001")
    assert new_cp.relationship_status == "new"
    assert new_cp.approved_master_card
    assert not new_cp.blocked
    established_cp = provider.get_counterparty_status("cp_002")
    assert established_cp.relationship_status == "established"
    assert established_cp.active_contract
    blocked_cp = provider.get_counterparty_status("cp_004")
    assert blocked_cp.relationship_status == "blocked"
    assert blocked_cp.blocked
    unknown_cp = provider.get_counterparty_status("cp_999")
    assert unknown_cp.relationship_status == "unknown"
    assert not unknown_cp.approved_master_card


def test_reconciliation_balances_payments_against_invoices() -> None:
    report = Mock1CConnector().reconcile_snapshot()
    assert report.balanced
    assert report.payments_without_invoice == 0
    assert report.invoiced_total > report.paid_total
    assert report.outstanding_total == report.invoiced_total - report.paid_total


def test_data_quality_counts_known_synthetic_anomalies() -> None:
    report = Mock1CConnector().calculate_data_quality()
    assert report.invoices_checked == 102
    # inv_001/inv_002 share a number; inv_003 breaks the tax base; inv_004
    # changes bank details; inv_005 has no contract (plus open-counterparty ones).
    assert report.duplicate_invoices == 1
    assert report.tax_mismatches == 1
    assert report.bank_fingerprint_mismatches == 1
    assert report.missing_contracts == 31
    assert report.completeness == round(1 - 34 / 102, 6)


def test_create_draft_is_disabled_by_default_and_never_posts() -> None:
    provider = Mock1CConnector()
    request = DraftCreateRequest(
        invoice_id="inv_100",
        counterparty_id="cp_010",
        amount=Decimal("1331.00"),
        purpose="Synthetic draft for the pilot",
    )
    with pytest.raises(DraftCapabilityDisabledError):
        provider.create_draft(request)

    enabled = Mock1CConnector(allow_draft_capability=True)
    result = enabled.create_draft(request)
    assert result.posted is False
    assert result.payment_executed is False
    assert result.draft_id.startswith("draft_synthetic_")
    assert result.draft_id == enabled.create_draft(request).draft_id  # idempotent

    with pytest.raises(ValueError, match="Unknown invoice"):
        enabled.create_draft(
            DraftCreateRequest(
                invoice_id="inv_999",
                counterparty_id="cp_001",
                amount=Decimal("1.00"),
                purpose="x",
            )
        )
    with pytest.raises(ValueError, match="exceeds"):
        enabled.create_draft(
            DraftCreateRequest(
                invoice_id="inv_100",
                counterparty_id="cp_010",
                amount=Decimal("9999.00"),
                purpose="over the invoice total",
            )
        )
