from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent import AgentResult
from app.models.digest import NonpaymentRisk

Money = Annotated[Decimal, Field(max_digits=18, decimal_places=2, ge=0)]
Currency = Literal["RUB"]


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str


class Counterparty(Record):
    name: str
    bank_fingerprint: str
    relationship_status: Literal["new", "established", "blocked"] = "new"
    first_seen_on: date | None = None
    successful_payment_count: int = Field(default=0, ge=0)
    last_reviewed_on: date | None = None
    risk_tier: Literal["standard", "elevated", "blocked"] = "standard"


class Contract(Record):
    counterparty_id: str
    currency: Currency = "RUB"
    ceiling: Money


class Invoice(Record):
    counterparty_id: str
    contract_id: str | None
    number: str
    issued_on: date
    due_on: date
    currency: Currency = "RUB"
    net: Money
    tax: Money
    gross: Money
    # Synthetic contractual rate, NOT a jurisdictional tax rule.
    tax_rate: Decimal = Field(ge=0, le=1, decimal_places=4)
    bank_fingerprint: str


class Payment(Record):
    invoice_id: str
    amount: Money
    paid_on: date
    currency: Currency = "RUB"


class Transaction(Record):
    booked_on: date
    direction: Literal["income", "expense"]
    amount: Money
    currency: Currency = "RUB"
    basis: Literal["cash"] = "cash"


class AccountBalance(Record):
    account_id: str
    account_name: str
    as_of: date
    amount: Money
    currency: Currency = "RUB"


class Receivable(Record):
    counterparty_id: str
    issued_on: date
    due_on: date
    gross: Money
    currency: Currency = "RUB"


class ReceivableReceipt(Record):
    receivable_id: str
    received_on: date
    amount: Money
    currency: Currency = "RUB"


class AccountingResult(AgentResult):
    mode: Literal["accounting_mock_v1"] = "accounting_mock_v1"
    dataset_version: str = "synthetic-accounting-rub-v7"
    invoice: Invoice | None = None
    counterparty: Counterparty | None = None
    paid: Money = Decimal("0")
    outstanding: Money = Decimal("0")
    checked_on: date
    method: str = "Decimal; ROUND_HALF_UP to RUB kopecks; no currency conversion"
    cash_in: Money = Decimal("0")
    cash_out: Money = Decimal("0")
    net_cash_flow: Decimal = Decimal("0")
    invoice_count: int = 0
    payment_count: int = 0
    overdue_count: int = 0
    # Dataset-level anomalies (duplicates, tax-base breaks) for the digest.
    anomaly_count: int = 0
    # Receivable analysis outputs (receivable_risk node / digest, TZ 6.2).
    receivable_total: Decimal = Decimal("0")
    expected_receipts: str = "0"
    receivable_aging: dict[str, str] = Field(default_factory=dict)
    nonpayment_risks: list[NonpaymentRisk] = Field(default_factory=list)
