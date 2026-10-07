"""Versioned server-owned execution contracts; not model-generated permissions."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProcessDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: int
    title: str
    result_owner_id: str
    # APR-006: admin never reviews business results; the process may name staff reviewers.
    reviewer_roles: tuple[str, ...] = ("owner",)
    acceptance_checks: tuple[str, ...]
    allowed_actions: tuple[str, ...] = ("analyze", "prepare_payment_draft")
    forbidden_actions: tuple[str, ...] = ("real_payment",)
    autonomy_level: Literal["review_required"] = "review_required"


def office_process(owner_id: str) -> ProcessDefinition:
    return ProcessDefinition(
        id="office_review",
        version=1,
        title="Проверка задачи AI-офисом",
        result_owner_id=owner_id,
        acceptance_checks=(
            "Проверены основания и ограничения результата",
            "Расхождения и недостающие сведения явно указаны",
            "Принятие результата не разрешает финансовые действия",
        ),
    )


class ResultReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rework_required", "rejected"]
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    result_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_node_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_rework_targets(self) -> "ResultReviewCreate":
        if self.decision == "rework_required" and not self.target_node_ids:
            raise ValueError("Select at least one graph node for rework")
        if self.decision != "rework_required" and self.target_node_ids:
            raise ValueError("Rework targets are only valid for rework_required")
        if len(set(self.target_node_ids)) != len(self.target_node_ids):
            raise ValueError("Rework node IDs must be unique")
        return self


GraphReadiness = Literal["ready", "blocked", "running", "completed", "failed", "cancelled"]


class ProcessGraphNode(BaseModel):
    """A materialized node in one task's execution graph."""

    id: str
    node_id: str | None = None
    kind: Literal["agent_step", "result_review"]
    agent: str | None = None
    action: str | None = None
    state: str
    readiness: GraphReadiness
    depends_on: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)


class ProcessGraph(BaseModel):
    task_id: str
    process_id: str | None = None
    process_version: int | None = None
    nodes: list[ProcessGraphNode]


class ProcessQualityReport(BaseModel):
    window_started: datetime
    completed_tasks: int
    reviewed_results: int
    pending_reviews: int
    review_rate: float = Field(ge=0, le=1)
    decisions: dict[str, int]
    average_review_seconds: int | None = Field(default=None, ge=0)


class ProcessControlReport(BaseModel):
    """Read-only operational controls for completed office results."""

    window_started: datetime
    office_results: int = Field(ge=0)
    postflight_completed: int = Field(ge=0)
    postflight_coverage: float = Field(ge=0, le=1)
    policy_decisions: dict[str, int]
    control_flags: dict[str, int]
