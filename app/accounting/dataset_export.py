"""Export the synthetic dataset to the 1C file-exchange CSV form.

One dataset shape feeds the golden registry, the mock, and the OneC file
provider - identical behavior is testable against the same numbers (TZ 8.2).
"""

import csv
from datetime import UTC, datetime
from pathlib import Path

from app.accounting.mock import Mock1CConnector


def export_dataset(directory: Path, provider: Mock1CConnector | None = None) -> Path:
    """Write the canonical CSV exchange files; returns the directory."""
    provider = provider or Mock1CConnector()
    directory.mkdir(parents=True, exist_ok=True)
    collections = {
        "counterparties": provider.list_counterparties(),
        "contracts": provider.list_contracts(),
        "invoices": provider.list_invoices(),
        "payments": provider.list_payments(),
        "transactions": provider.list_transactions(),
        "account_balances": provider.list_accounts(),
        "receivables": provider.list_receivables(),
        "receivable_receipts": provider.list_receivable_receipts(),
    }
    for name, rows in collections.items():
        fields = list(type(rows[0]).model_fields)
        with (directory / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: (
                            ""
                            if value is None
                            else value.isoformat()
                            if hasattr(value, "isoformat")
                            else str(value)
                        )
                        for key, value in row.model_dump().items()
                        if key in fields
                    }
                )
    journal = provider.accrual_journal()
    if journal is not None:
        fields = list(AccrualEntry_FIELDS)
        with (directory / "accrual_journal.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for entry in journal.entries:
                writer.writerow(
                    {
                        key: ("" if value is None else str(value))
                        for key, value in entry.model_dump().items()
                        if key in fields
                    }
                )
    return directory


from app.models.accrual import AccrualEntry  # noqa: E402

AccrualEntry_FIELDS = list(AccrualEntry.model_fields)

# The export moment is recorded next to the data for the watermark.
EXPORT_WATERMARK_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def export_watermark(directory: Path, moment: datetime | None = None) -> datetime:
    moment = moment or datetime.now(UTC)
    (directory / "watermark.txt").write_text(moment.astimezone(UTC).isoformat(), encoding="utf-8")
    return moment
