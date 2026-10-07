from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.agent import AgentResult
from app.models.digest import DailyOwnerDigest
from app.models.enums import AgentType, RiskLevel, TaskCategory, TaskState
from app.models.knowledge import Jurisdiction
from app.models.legal import LegalResult
from app.models.office import OfficeResult
from app.models.process import ProcessDefinition
from app.orchestrator.contracts import ProcessDefinitionV2, RunBudget, RunUsage
from app.orchestrator.passport import ProcessDefinitionV3


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=20_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)
    requested_agent: AgentType | None = None
    jurisdiction: Jurisdiction | None = None
    effective_on: date | None = None
    invoice_id: str | None = Field(default=None, pattern=r"^inv_[0-9]{3}$")
    requested_action: Literal["analyze", "prepare_payment_draft"] = "analyze"
    process_id: Literal["office_review", "daily_cash_and_receivable_risk"] = "office_review"

    @model_validator(mode="after")
    def require_invoice_for_draft(self) -> "TaskCreate":
        if self.requested_action == "prepare_payment_draft" and self.invoice_id is None:
            raise ValueError("Select a synthetic invoice before requesting a draft")
        return self

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be blank")
        return value


class LegalClarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jurisdiction: Jurisdiction
    effective_on: date


class DailyControlCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_on: date | None = None


class RoutingDecision(BaseModel):
    category: TaskCategory
    confidence: float = Field(ge=0, le=1)
    required_agents: list[AgentType]
    requires_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    reason_code: str | None = None


class TaskStepPlan(BaseModel):
    step_id: str
    node_id: str | None = Field(default=None, min_length=1, max_length=80)
    agent: AgentType
    action: str
    depends_on: list[str] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    max_attempts: int = Field(default=1, ge=1, le=3)
    retryable_error_codes: list[str] = Field(default_factory=list)
    backoff_seconds: float = Field(default=0.5, ge=0, le=30)
    risk_level: RiskLevel
    expected_output_schema: str
    estimated_llm_calls: int = Field(default=0, ge=0, le=10)
    estimated_cost_rub: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str
    state: TaskState
    category: TaskCategory | None = None
    risk_level: RiskLevel | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    result: OfficeResult | LegalResult | DailyOwnerDigest | AgentResult | None = None
    process: ProcessDefinition | ProcessDefinitionV2 | ProcessDefinitionV3 | None = None
    run_budget: RunBudget | None = None
    run_usage: RunUsage | None = None
    rework_parent_task_id: str | None = None
    rework_target_node_ids: list[str] = Field(default_factory=list)
    rework_cycle: int = Field(default=0, ge=0)

    @field_validator("created_at", "updated_at", "completed_at")
    @classmethod
    def normalize_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
