from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.knowledge.embeddings import RETRIEVAL_VERSION

Jurisdiction = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z]{2}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
SourceStatus = Literal["DRAFT", "APPROVED", "ACTIVE", "SUPERSEDED", "EXPIRED", "REVOKED"]
Classification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]


class SourceCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "artifact_id": "art_01JZK4Q9T2XW8V5R3N6Y7B0C",
                    "title": "НК РФ, часть первая",
                    "jurisdiction": "RU",
                    "document_type": "code",
                    "authority": "Государственная Дума РФ",
                    "version": "2026-01-01",
                    "effective_from": "2026-01-01",
                    "effective_to": None,
                    "status": "ACTIVE",
                    "classification": "PUBLIC",
                    "language": "ru",
                }
            ]
        },
    )

    artifact_id: str = Field(
        min_length=1,
        max_length=40,
        description="Id returned by POST /api/v1/files after the DLP scan.",
    )
    title: Label
    jurisdiction: Jurisdiction = Field(description="ISO-3166 alpha-2.", examples=["RU"])
    document_type: Label = Field(description="'code', 'fz', 'letter', 'ruling', ….")
    authority: Label
    version: Label
    effective_from: date
    effective_to: date | None = None
    status: SourceStatus = "DRAFT"
    classification: Classification = Field(
        default="INTERNAL",
        description=(
            "Server re-computes this from DLP findings; a client-supplied "
            "value is treated as a hint and the stricter class wins."
        ),
    )
    language: str = Field(default="ru", pattern=r"^[a-z]{2}$")

    @model_validator(mode="after")
    def valid_interval(self) -> Self:
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from (inclusive)")
        return self


class SourceResponse(SourceCreate):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    sha256: str
    embedding_model: str
    embedding_dimensions: int = 128
    chunk_count: int
    reindex_of_id: str | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "query": "какие документы подтверждают право на вычет НДС",
                    "jurisdiction": "RU",
                    "effective_on": "2026-01-01",
                    "document_types": ["code"],
                    "top_k": 5,
                }
            ]
        },
    )

    query: str = Field(min_length=1, max_length=20_000, pattern=r"\S")
    jurisdiction: Jurisdiction = Field(examples=["RU"])
    effective_on: date = Field(
        description="Only sources whose effective interval covers this date are retrieved."
    )
    document_types: list[Label] = Field(default_factory=list, max_length=20)
    top_k: int = Field(default=5, ge=1, le=50)


class SearchHit(BaseModel):
    source_id: str
    chunk_id: str
    title: str
    version: str
    jurisdiction: str
    document_type: str
    authority: str
    effective_from: date
    effective_to: date | None
    text: str
    locator: str
    page: int | None
    article: str | None
    score: float


class SearchResponse(BaseModel):
    hits: list[SearchHit]
    embedding_model: str
    embedding_dimensions: int = 128
    retrieval_version: str = RETRIEVAL_VERSION
    warnings: list[str] = Field(
        default_factory=lambda: [
            "MOCK_EMBEDDINGS: lexical-gated token-hash ranking is not semantic legal retrieval."
        ]
    )
