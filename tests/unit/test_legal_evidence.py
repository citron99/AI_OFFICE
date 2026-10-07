from datetime import date

import pytest
from pydantic import ValidationError

from app.models.enums import AgentType
from app.models.knowledge import SearchHit
from app.models.legal import DocumentExcerpt, EvidenceAssessment, LegalDraft, LegalResult
from app.services.legal_analysis import validate_assessment, validate_draft


def result() -> LegalResult:
    return LegalResult(
        agent=AgentType.LAWYER,
        status="retrieval_only",
        summary="test",
        jurisdiction="LV",
        effective_on=date(2026, 8, 27),
        evidence=[
            SearchHit(
                source_id="src1",
                chunk_id="chunk1",
                title="Synthetic law",
                version="1",
                jurisdiction="LV",
                document_type="test_norm",
                authority="Synthetic fixture",
                effective_from=date(2026, 1, 1),
                effective_to=None,
                text="Notice must be in writing.",
                locator="Article 1",
                page=None,
                article="1",
                score=1,
            )
        ],
        documents=[
            DocumentExcerpt(
                excerpt_id="art1:0",
                artifact_id="art1",
                filename="contract.txt",
                sha256="0" * 64,
                locator="text; part 1",
                text="Verbal notice is sufficient.",
            )
        ],
    )


def draft(**changes: object) -> dict[str, object]:
    return {
        "findings": [
            {
                "title": "Notice",
                "description": "Check notice form.",
                "risk_level": "high",
                "references": [
                    {
                        "kind": "source",
                        "reference_id": "chunk1",
                        "quote": "Notice must be in writing.",
                    },
                    {
                        "kind": "document",
                        "reference_id": "art1:0",
                        "quote": "Verbal notice is sufficient.",
                    },
                ],
                **changes,
            }
        ]
    }


def test_verified_locations_are_server_derived() -> None:
    findings = validate_draft(LegalDraft.model_validate(draft()), result())
    assert len(findings) == 1
    assert findings[0].citations[0].source_id == "src1"
    assert findings[0].citations[0].locator == "Article 1"
    assert findings[0].citations[1].source_id == "art1"


@pytest.mark.parametrize(
    "kind,reference_id,quote",
    [
        ("source", "unknown", "Notice must be in writing."),
        ("source", "chunk1", "Notice need not be in writing."),
        ("source", "chunk1", "          "),
        ("document", "foreign:0", "Verbal notice is sufficient."),
        ("document", "art1:0", "Written notice is sufficient."),
    ],
)
def test_invalid_citation_fails_closed(kind: str, reference_id: str, quote: str) -> None:
    model = LegalDraft.model_validate(draft())
    target = 0 if kind == "source" else 1
    model.findings[0].references[target].reference_id = reference_id
    model.findings[0].references[target].quote = quote
    with pytest.raises(ValueError):
        validate_draft(model, result())


@pytest.mark.parametrize("keep", [0, 1])
def test_cannot_replace_law_with_contract_or_omit_contract(keep: int) -> None:
    model = LegalDraft.model_validate(draft())
    model.findings[0].references = [model.findings[0].references[keep]]
    with pytest.raises(ValueError):
        validate_draft(model, result())


def test_missing_or_extra_fields_are_rejected() -> None:
    for payload in [{}, {"findings": [], "summary": "Everything is legal"}, draft(references=[])]:
        with pytest.raises(ValidationError):
            LegalDraft.model_validate(payload)


def assessment(**changes: object) -> EvidenceAssessment:
    return EvidenceAssessment.model_validate(
        {
            "status": "sufficient",
            "rationale": "Synthetic assessment.",
            "missing_information": [],
            "references": [
                {
                    "kind": "source",
                    "reference_id": "chunk1",
                    "quote": "Notice must be in writing.",
                }
            ],
            **changes,
        }
    )


def test_valid_assessment_and_legacy_result() -> None:
    validate_assessment(assessment(), result())
    assert result().evidence_assessment is None
    assert result().evidence_assessment_version is None


@pytest.mark.parametrize(
    "changes",
    [
        {"rationale": "   "},
        {"references": []},
        {"missing_information": ["Missing law"]},
        {"status": "partial"},
        {"status": "insufficient"},
        {"status": "partial", "missing_information": [" "]},
        {"status": "partial", "missing_information": ["x" * 1001]},
        {
            "references": [
                {"kind": "source", "reference_id": "foreign", "quote": "Notice must be in writing."}
            ]
        },
        {
            "references": [
                {"kind": "source", "reference_id": "chunk1", "quote": "Notice may be verbal."}
            ]
        },
        {
            "references": [
                {
                    "kind": "document",
                    "reference_id": "art1:0",
                    "quote": "Verbal notice is sufficient.",
                }
            ]
        },
    ],
)
def test_assessment_inconsistencies_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        validate_assessment(assessment(**changes), result())


def test_missing_sources_can_be_reported_without_inventing_references() -> None:
    validate_assessment(
        assessment(
            status="insufficient",
            missing_information=["Applicable provision required."],
            references=[],
        ),
        result(),
    )
