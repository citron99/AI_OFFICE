from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.consultant_plus.models import ConsultantPlusTrail
from app.llm.telemetry import ModelCallInfo
from app.models.agent import AgentResult
from app.models.enums import RiskLevel
from app.models.knowledge import SearchHit


class DocumentExcerpt(BaseModel):
    excerpt_id: str
    artifact_id: str
    filename: str
    sha256: str
    locator: str
    text: str


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["source", "document"]
    reference_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=8, max_length=1600)


class LegalDraftFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    risk_level: RiskLevel
    references: list[EvidenceReference] = Field(min_length=1, max_length=10)


class LegalDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    findings: list[LegalDraftFinding] = Field(max_length=20)


class EvidenceAssessment(BaseModel):
    """Provider judgement, not a server-verified legal conclusion."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["sufficient", "partial", "insufficient"]
    rationale: str = Field(min_length=1, max_length=2000)
    missing_information: list[str] = Field(max_length=10)
    references: list[EvidenceReference] = Field(max_length=10)


class LegalResult(AgentResult):
    mode: Literal["legal_retrieval_pilot", "legal_analysis_pilot"] = "legal_retrieval_pilot"
    jurisdiction: str | None
    effective_on: date | None
    legal_sources_found: bool = False
    evidence: list[SearchHit] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    specialist_review_recommended: bool = True
    documents: list[DocumentExcerpt] = Field(default_factory=list)
    verified_references: list[EvidenceReference] = Field(default_factory=list)
    analysis_model: str = "none-retrieval-only"
    analysis_attempted: bool = False
    model_calls: list[ModelCallInfo] = Field(default_factory=list)
    evidence_assessment: EvidenceAssessment | None = None
    evidence_assessment_version: str | None = None
    # Mandatory Consultant+ search trail (LEG-001, LEG-008).
    consultant_plus: ConsultantPlusTrail | None = None
    # Old persisted results must not be relabelled as a newer retrieval algorithm.
    retrieval_version: str = "mock-hash-v1"
