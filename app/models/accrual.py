from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.accounting import Currency, Money, Record


class AccrualEntry(Record):
    recognized_on: date
    category: Literal["revenue", "cost_of_sales", "operating_expense", "depreciation"]
    amount: Money
    reversal: bool = False
    currency: Currency = "RUB"
    source_reference: str
    description: str


class AccrualJournal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: str
    coverage_start: date
    coverage_end: date
    entries: tuple[AccrualEntry, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> "AccrualJournal":
        if self.coverage_end < self.coverage_start:
            raise ValueError("Invalid journal coverage")
        if len({e.id for e in self.entries}) != len(self.entries):
            raise ValueError("Duplicate accrual entry ID")
        if any(
            not self.coverage_start <= e.recognized_on <= self.coverage_end for e in self.entries
        ):
            raise ValueError("Entry outside journal coverage")
        return self
