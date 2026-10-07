from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.accounting import AccountBalance, Money
from app.models.accrual import AccrualEntry


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date
    planned_cash_in: Money | None = None
    planned_cash_out: Money | None = None

    @model_validator(mode="after")
    def valid_period(self) -> "ReportRequest":
        if self.end < self.start:
            raise ValueError("Period end must not precede start")
        if (self.end - self.start).days > 365:
            raise ValueError("Period must not exceed 366 days")
        if self.start.toordinal() <= (self.end - self.start).days + 1:
            raise ValueError("Previous comparison period is outside the supported date range")
        if (self.planned_cash_in is None) != (self.planned_cash_out is None):
            raise ValueError("Both planned cash inflow and outflow are required")
        return self


class CashPeriod(BaseModel):
    start: date
    end: date
    incoming: Decimal
    outgoing: Decimal
    net: Decimal
    transaction_ids: list[str]


class PlanFact(BaseModel):
    basis: Literal["user_supplied_cash_plan"] = "user_supplied_cash_plan"
    planned_incoming: Decimal
    planned_outgoing: Decimal
    incoming_variance: Decimal
    outgoing_variance: Decimal
    net_variance: Decimal


class Payable(BaseModel):
    invoice_id: str
    counterparty_id: str
    due_on: date
    gross: Decimal
    paid: Decimal
    outstanding: Decimal
    overpayment: Decimal
    days_overdue: int
    payment_ids: list[str]


class ReceivablePosition(BaseModel):
    receivable_id: str
    counterparty_id: str
    due_on: date
    gross: Decimal
    received: Decimal
    outstanding: Decimal
    days_overdue: int
    receipt_ids: list[str]
    overpayment: Decimal


class ProfitPeriod(BaseModel):
    start: date
    end: date
    revenue: Decimal
    cost_of_sales: Decimal
    gross_profit: Decimal
    operating_expense: Decimal
    depreciation: Decimal
    operating_profit: Decimal
    entries: list[AccrualEntry]


class ProfitAndLoss(BaseModel):
    journal_version: str
    coverage_start: date
    coverage_end: date
    basis: Literal["synthetic_accrual_excluding_vat"] = "synthetic_accrual_excluding_vat"
    current: ProfitPeriod | None
    previous: ProfitPeriod | None
    operating_profit_change: Decimal | None
    warnings: list[str]


class FinanceReport(BaseModel):
    dataset_version: str
    currency: Literal["RUB"] = "RUB"
    method: str = "Decimal; inclusive dates; previous period of equal length; no FX conversion"
    current: CashPeriod
    previous: CashPeriod
    net_change: Decimal
    plan_fact: PlanFact | None = None
    payables_as_of: date
    payables: list[Payable]
    aging: dict[str, Decimal]
    total_outstanding: Decimal
    total_overpayment: Decimal
    balances_as_of: date | None
    account_balance_dates: dict[str, date]
    account_balances: list[AccountBalance]
    total_bank_balance: Decimal | None
    receivables_as_of: date
    receivables: list[ReceivablePosition]
    receivable_aging: dict[str, Decimal]
    total_receivable: Decimal
    profit_and_loss: ProfitAndLoss | None = None
    warnings: list[str] = Field(
        default_factory=lambda: [
            "SYNTHETIC_DATA_ONLY",
            "POINT_IN_TIME_BALANCES: bank balances use the latest synthetic "
            "snapshot on or before report end.",
            "UNRECONCILED_FIXTURE: cash transactions and invoice payments are "
            "separate test datasets.",
            "SOURCE_ANOMALIES_INCLUDED: report is not approval; invoice "
            "validation remains mandatory.",
        ]
    )
