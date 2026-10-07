"""Accounting-provider composition root; business services never pick a connector."""

from app.accounting.mock import Mock1CConnector
from app.accounting.provider import AccountingProvider
from app.config import Settings


class AccountingProviderFactory:
    def create(self, settings: Settings) -> AccountingProvider:
        if settings.accounting_provider == "mock":
            return Mock1CConnector()
        if settings.accounting_provider == "onec_file":
            from datetime import UTC, datetime
            from pathlib import Path

            from app.accounting.onec_file import OneCFileExchangeProvider

            if settings.onec_exchange_dir is None:
                raise RuntimeError("accounting_provider=onec_file requires ONEC_EXCHANGE_DIR")
            directory = Path(settings.onec_exchange_dir)
            watermark_path = directory / "watermark.txt"
            watermark = (
                datetime.fromisoformat(watermark_path.read_text(encoding="utf-8").strip())
                if watermark_path.is_file()
                else datetime.now(UTC)
            )
            return OneCFileExchangeProvider(exchange_dir=directory, watermark=watermark)
        raise RuntimeError(
            "1C network connector is not enabled in this release; "
            "use accounting_provider=mock or onec_file"
        )
