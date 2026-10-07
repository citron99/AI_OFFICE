"""Data Egress Gateway: the last gate before any external provider (TZ 10.3).

The gateway runs before every external call (external LLM first of all). It
maps the detected data class, the requested route and the company scope to an
ALLOW/BLOCK decision from a static policy matrix; it logs the decision and a
content hash, never the content itself. LLM output can never change the
decision.
"""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field

from app.security.data_classification import ClassificationResult, DataClass, classify_text

EgressDecision = Literal["allow", "block"]


class EgressRequest(BaseModel):
    model_config = {"extra": "forbid"}

    company_id: str = Field(min_length=1, max_length=40)
    task_id: str | None = None
    route: Literal["external_llm", "local_llm", "internal_only"] = "external_llm"
    purpose: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=1)


class EgressVerdict(BaseModel):
    decision: EgressDecision
    data_class: DataClass
    content_hash: str
    reasons: list[str] = Field(default_factory=list)
    decided_at: datetime
    policy_version: str = "tz-v2.1-egress-v1"


# TZ 10.2 route matrix: which classes may ever leave to the external LLM.
_EXTERNAL_ALLOWED: frozenset[DataClass] = frozenset({DataClass.PUBLIC, DataClass.INTERNAL})
# PERSONAL requires the approved purpose+minimization contour of TZ 10.2 and is
# therefore not part of the MVP external set; CONFIDENTIAL/RESTRICTED never go.


def evaluate_egress(request: EgressRequest) -> EgressVerdict:
    classification: ClassificationResult = classify_text(request.content)
    content_hash = sha256(request.content.encode()).hexdigest()
    reasons: list[str] = []
    decision: EgressDecision = "allow"

    if request.route == "external_llm":
        if classification.data_class == DataClass.RESTRICTED:
            decision = "block"
            reasons.append("RESTRICTED_DATA_EXTERNAL_LLM_FORBIDDEN")
        elif classification.data_class == DataClass.CONFIDENTIAL:
            decision = "block"
            reasons.append("CONFIDENTIAL_DATA_REQUIRES_LOCAL_CONTOUR")
        elif classification.data_class == DataClass.PERSONAL:
            decision = "block"
            reasons.append("PERSONAL_DATA_REQUIRES_APPROVED_ROUTE_AND_MINIMIZATION")
        elif classification.data_class not in _EXTERNAL_ALLOWED:
            decision = "block"
            reasons.append("DATA_CLASS_NOT_ALLOWED_EXTERNAL")
    elif request.route == "internal_only" and classification.data_class == DataClass.RESTRICTED:
        # Even internal storage of raw secrets is a blocked egress event.
        decision = "block"
        reasons.append("RESTRICTED_DATA_NO_STORAGE")

    return EgressVerdict(
        decision=decision,
        data_class=classification.data_class,
        content_hash=content_hash,
        reasons=reasons or ["ROUTE_ALLOWED_FOR_DATA_CLASS"],
        decided_at=datetime.now(UTC),
    )
