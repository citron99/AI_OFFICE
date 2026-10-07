from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.knowledge import Jurisdiction


class LegalChangeRadarCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_source_id: str = Field(min_length=1, max_length=40)
    current_source_id: str = Field(min_length=1, max_length=40)
    subject: str = Field(min_length=3, max_length=2000)
    jurisdiction: Jurisdiction
    effective_on: date

    @model_validator(mode="after")
    def distinct_sources(self) -> "LegalChangeRadarCreate":
        if self.baseline_source_id == self.current_source_id:
            raise ValueError("baseline and current sources must be different")
        return self


class LegalChangeCitation(BaseModel):
    source_id: str
    title: str
    version: str
    locator: str
    quote: str


class LegalChangeItem(BaseModel):
    change_id: str
    change_type: Literal["added", "removed", "modified"]
    impact_signal: Literal["high_attention", "review", "informational"]
    summary: str
    matched_terms: list[str]
    before: LegalChangeCitation | None = None
    after: LegalChangeCitation | None = None


class LegalChangeRadarResult(BaseModel):
    status: Literal["awaiting_legal_review", "no_text_change"]
    disclaimer: str
    jurisdiction: str
    effective_on: date
    baseline: dict[str, Any]
    current: dict[str, Any]
    changes: list[LegalChangeItem]
    counts: dict[str, int]
    consultant_plus: dict[str, Any]
    warnings: list[str]


class LegalChangeReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "changes_requested", "rejected"]
    reason: str = Field(min_length=8, max_length=2000)


class LegalChangeReviewResponse(LegalChangeReviewCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reviewer_id: str
    created_at: datetime


class LegalChangeRadarRunResponse(BaseModel):
    id: str
    baseline_source_id: str
    current_source_id: str
    subject: str
    jurisdiction: str
    effective_on: date
    status: str
    result: LegalChangeRadarResult
    created_at: datetime
    review: LegalChangeReviewResponse | None = None
