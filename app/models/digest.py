"""DailyOwnerDigest: the accepted result schema of the daily pilot (TZ 6.2)."""

from datetime import date

from pydantic import BaseModel, Field

from app.models.agent import AgentResult

DIGEST_VERSION = "daily_owner_digest_v1"


class NonpaymentRisk(BaseModel):
    counterparty_id: str
    counterparty_name: str
    outstanding: str
    days_overdue: int
    explanation: str
    recommended_action: str


class DailyOwnerDigest(AgentResult):
    mode: str = DIGEST_VERSION
    digest_date: date
    watermark: str
    cash_available: str
    cash_in: str
    cash_out: str
    net_cash_flow: str
    expected_receipts: str
    receivable_total: str
    receivable_aging: dict[str, str] = Field(default_factory=dict)
    top_nonpayment_risks: list[NonpaymentRisk] = Field(default_factory=list)
    anomaly_count: int = 0
    invoice_count: int = 0
