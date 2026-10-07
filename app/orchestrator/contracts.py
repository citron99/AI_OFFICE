"""Server-owned executable process contracts and bounded run budgets."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AgentType, RiskLevel


class RetryPolicy(BaseModel):
    """A bounded retry contract declared by the process author."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=3)
    retryable_error_codes: tuple[str, ...] = ()


class RunBudget(BaseModel):
    """Hard, persisted limits for a single process run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_steps: int = Field(default=8, ge=1, le=100)
    max_llm_calls: int = Field(default=2, ge=0, le=50)
    max_rework_cycles: int = Field(default=2, ge=0, le=10)
    max_runtime_seconds: int = Field(default=120, ge=1, le=3_600)
    max_input_tokens: int = Field(default=100_000, ge=0)
    max_output_tokens: int = Field(default=20_000, ge=0)
    max_cost_rub: Decimal = Field(default=Decimal("100.00"), ge=Decimal("0"))


class RunUsage(BaseModel):
    """Additive counters written to the task before and after every node."""

    model_config = ConfigDict(extra="forbid")

    steps_started: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    rework_cycles: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reserved_cost_rub: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    observed_cost_rub: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    started_at: datetime | None = None

    def runtime_seconds(self, now: datetime) -> int:
        if self.started_at is None:
            return 0
        started = (
            self.started_at.replace(tzinfo=UTC)
            if self.started_at.tzinfo is None
            else self.started_at.astimezone(UTC)
        )
        return max(0, round((now.astimezone(UTC) - started).total_seconds()))


class ProcessNodeSpec(BaseModel):
    """Stable node identity and its typed execution contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    agent: AgentType
    action: str = Field(min_length=1, max_length=200)
    depends_on: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    risk_level: RiskLevel = RiskLevel.MEDIUM
    expected_output_schema: str = Field(min_length=1, max_length=100)
    retry_policy: RetryPolicy = RetryPolicy()
    estimated_llm_calls: int = Field(default=0, ge=0, le=10)
    estimated_cost_rub: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class ProcessDefinitionV2(BaseModel):
    """An executable, review-required process definition.

    It is application configuration rather than model-generated instructions and
    is snapshotted on a task before its first node starts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: Literal[2] = 2
    title: str
    result_owner_id: str
    # APR-006: admin never reviews business results; the process may name staff reviewers.
    reviewer_roles: tuple[str, ...] = ("owner",)
    acceptance_checks: tuple[str, ...]
    allowed_actions: tuple[str, ...] = ("analyze", "prepare_payment_draft")
    forbidden_actions: tuple[str, ...] = ("real_payment",)
    autonomy_level: Literal["review_required"] = "review_required"
    nodes: tuple[ProcessNodeSpec, ...] = Field(min_length=1)
    run_budget: RunBudget

    @model_validator(mode="after")
    def validate_graph(self) -> "ProcessDefinitionV2":
        nodes = {node.id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError("Process definition contains duplicate node IDs")
        for node in self.nodes:
            unknown = set(node.depends_on) - nodes.keys()
            if unknown:
                raise ValueError(f"Process node {node.id} has unknown dependencies")
            if node.id in node.depends_on:
                raise ValueError(f"Process node {node.id} cannot depend on itself")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("Process definition contains a dependency cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in nodes[node_id].depends_on:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in nodes:
            visit(node_id)
        return self
