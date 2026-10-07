"""ProcessDefinitionV3: the executable graph plus the process passport (TZ 3.2).

A V3 passport is a superset of the executable V2 contract: the same nodes,
dependencies, retry policies and run budgets, plus the owner-facing passport
fields - trigger, result owner role, acceptance criteria, allowed sources,
stop conditions, escalation, manual fallback, the autonomy ceiling and the
policy/output schema versions the run was accepted against.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.orchestrator.contracts import ProcessNodeSpec, RunBudget

AutonomyCeiling = Literal["a0_shadow", "a1_recommendation", "a2_draft", "a3_approved_action"]

_SEVERITY = {
    level: index
    for index, level in enumerate(
        ("a0_shadow", "a1_recommendation", "a2_draft", "a3_approved_action")
    )
}


def autonomy_rank(level: str) -> int:
    if level not in _SEVERITY:
        raise ValueError(f"Unknown autonomy level: {level}")
    return _SEVERITY[level]


class ProcessPassport(BaseModel):
    """The owner-facing contract fixed before any automation is allowed (TZ 3.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger: str = Field(min_length=3, max_length=300)
    recipient: str = Field(min_length=1, max_length=200)
    result: str = Field(min_length=3, max_length=500)
    owner: str = Field(min_length=1, max_length=200)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1, max_length=10)
    allowed_sources: tuple[str, ...] = Field(min_length=1, max_length=10)
    allowed_capabilities: tuple[str, ...] = Field(min_length=1, max_length=20)
    stop_conditions: tuple[str, ...] = Field(min_length=1, max_length=10)
    escalation: str = Field(min_length=3, max_length=300)
    rollback: str = Field(min_length=3, max_length=300)
    manual_fallback: str = Field(min_length=3, max_length=500)
    autonomy_ceiling: AutonomyCeiling = "a2_draft"
    metrics: tuple[str, ...] = Field(min_length=1, max_length=10)


class ProcessDefinitionV3(BaseModel):
    """V2 executable graph + immutable V3 passport, snapshotted per run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: Literal[3] = 3
    title: str
    result_owner_id: str
    reviewer_roles: tuple[str, ...] = ("owner",)
    acceptance_checks: tuple[str, ...]
    allowed_actions: tuple[str, ...] = ("analyze", "prepare_payment_draft")
    forbidden_actions: tuple[str, ...] = ("real_payment",)
    autonomy_level: AutonomyCeiling = "a2_draft"
    enabled: bool = True
    policy_version: str
    output_schema_version: str
    nodes: tuple[ProcessNodeSpec, ...] = Field(min_length=1)
    run_budget: RunBudget
    passport: ProcessPassport

    @model_validator(mode="after")
    def validate_contract(self) -> "ProcessDefinitionV3":
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

        # The passport must cover exactly the nodes that execute.
        node_ids = {node.id for node in self.nodes}
        unknown_capabilities = set(self.passport.allowed_capabilities) - node_ids
        if unknown_capabilities:
            raise ValueError(
                f"Passport allows unknown capabilities: {sorted(unknown_capabilities)}"
            )
        return self

    def allows_autonomy(self, requested: str) -> bool:
        """A runtime level may never exceed the passport ceiling (TZ 7.1)."""

        return autonomy_rank(requested) <= autonomy_rank(self.autonomy_level)


def load_passport(path: Path) -> ProcessDefinitionV3:
    """Load and validate a versioned passport JSON file."""

    import json

    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return ProcessDefinitionV3.model_validate(data)


PASSPORT_DIR = Path(__file__).resolve().parents[2] / "processes"


def available_passports(directory: Path | None = None) -> list[ProcessDefinitionV3]:
    """Load every versioned passport shipped with the application."""

    directory = directory or PASSPORT_DIR
    passports: list[ProcessDefinitionV3] = []
    if not directory.exists():
        return passports
    for path in sorted(directory.glob("*.v3.json")):
        passports.append(load_passport(path))
    return passports


def passport_for(process_id: str, directory: Path | None = None) -> ProcessDefinitionV3 | None:
    for passport in available_passports(directory):
        if passport.id == process_id:
            return passport
    return None
