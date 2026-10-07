"""OneC file-exchange provider: identical behavior to the mock (D-05, TZ 8.2).

The synthetic dataset is exported to the canonical CSV exchange form; the
OneCFileExchangeProvider must produce the same numbers the mock does -
"identical behavior for Mock and production adapter" is enforced, not
assumed (TZ 13.1 contract testing).
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.accounting.dataset_export import export_dataset, export_watermark
from app.accounting.mock import Mock1CConnector
from app.accounting.onec_file import OneCFileExchangeProvider
from app.config import Settings
from app.main import create_app


@pytest.fixture
async def onec_provider(tmp_path: Path) -> OneCFileExchangeProvider:
    directory = export_dataset(tmp_path / "exchange")
    export_watermark(directory, datetime.now(UTC))
    return OneCFileExchangeProvider(exchange_dir=directory, watermark=datetime.now(UTC))


def test_exchange_dataset_matches_mock_counts(onec_provider: OneCFileExchangeProvider) -> None:
    mock = Mock1CConnector()
    assert onec_provider.sync_read_only().counts == mock.sync_read_only().counts


def test_exchange_invoice_numbers_match_mock(onec_provider: OneCFileExchangeProvider) -> None:
    mock_invoice = Mock1CConnector().list_invoices()[99]
    exchange_invoice = next(i for i in onec_provider.list_invoices() if i.id == mock_invoice.id)
    assert exchange_invoice.gross == mock_invoice.gross
    assert exchange_invoice.tax == mock_invoice.tax
    assert exchange_invoice.counterparty_id == mock_invoice.counterparty_id


def test_exchange_healthcheck_and_watermark(onec_provider: OneCFileExchangeProvider) -> None:
    health = onec_provider.healthcheck()
    assert health.status == "ok"
    watermark = onec_provider.get_sync_watermark()
    assert watermark.source == "1c_production"
    assert watermark.generated_at.tzinfo is not None


def test_exchange_counterparty_status_matches_mock(
    onec_provider: OneCFileExchangeProvider,
) -> None:
    mock_status = Mock1CConnector().get_counterparty_status("cp_002")
    exchange_status = onec_provider.get_counterparty_status("cp_002")
    assert exchange_status.relationship_status == mock_status.relationship_status
    assert exchange_status.active_contract == mock_status.active_contract
    assert exchange_status.blocked == mock_status.blocked


def test_exchange_reconciliation_matches_mock(onec_provider: OneCFileExchangeProvider) -> None:
    mock_report = Mock1CConnector().reconcile_snapshot()
    exchange_report = onec_provider.reconcile_snapshot()
    assert exchange_report.balanced == mock_report.balanced
    assert exchange_report.payments_without_invoice == mock_report.payments_without_invoice
    assert exchange_report.outstanding_total == mock_report.outstanding_total


def test_exchange_incomplete_directory_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="file exchange incomplete"):
        OneCFileExchangeProvider(exchange_dir=tmp_path, watermark=datetime.now(UTC))


def test_exchange_create_draft_disabled(onec_provider: OneCFileExchangeProvider) -> None:
    from decimal import Decimal

    from app.accounting.provider import DraftCapabilityDisabledError, DraftCreateRequest

    with pytest.raises(DraftCapabilityDisabledError):
        onec_provider.create_draft(
            DraftCreateRequest(
                invoice_id="inv_100",
                counterparty_id="cp_010",
                amount=Decimal("1331.00"),
                purpose="x",
            )
        )


def test_factory_requires_exchange_dir(tmp_path: Path) -> None:
    from app.accounting.factory import AccountingProviderFactory

    with pytest.raises(RuntimeError, match="ONEC_EXCHANGE_DIR"):
        AccountingProviderFactory().create(
            Settings(app_env="test", accounting_provider="onec_file")
        )
    directory = export_dataset(tmp_path / "exchange")
    export_watermark(directory)
    provider = AccountingProviderFactory().create(
        Settings(
            app_env="test",
            accounting_provider="onec_file",
            onec_exchange_dir=str(directory),
        )
    )
    assert provider.get_sync_watermark().source == "1c_production"


async def test_app_runs_with_onec_file_provider(engine, tmp_path: Path) -> None:
    """The whole app boots and serves accounting over the file exchange."""
    import httpx

    directory = export_dataset(tmp_path / "exchange")
    export_watermark(directory)
    settings = Settings(
        app_env="test",
        accounting_provider="onec_file",
        onec_exchange_dir=str(directory),
        upload_dir=tmp_path / "uploads",
        llm_provider="mock",
        embedding_provider="mock",
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory_ok(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            status = await client.get("/api/v1/accounting/status")
            assert status.status_code == 200, status.text
            report = await client.post(
                "/api/v1/accounting/financial-report",
                json={"start": "2026-07-01", "end": "2026-07-31"},
            )
            assert report.status_code == 200, report.text
            assert report.json()["current"]["net"] == "-148500.00"


def create_session_factory_ok(engine):
    from app.db.session import create_session_factory

    return create_session_factory(engine)
