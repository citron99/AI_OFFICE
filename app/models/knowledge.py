from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.knowledge.embeddings import RETRIEVAL_VERSION

Jurisdiction = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z]{2}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
SourceStatus = Literal["DRAFT", "APPROVED", "ACTIVE", "SUPERSEDED", "EXPIRED", "REVOKED"]
Classification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=40)
    title: Label
    jurisdiction: Jurisdiction
    document_type: Label
    authority: Label
    version: Label
    effective_from: date
    effective_to: date | None = None
    status: SourceStatus = "DRAFT"
    classification: Classification = "INTERNAL"
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
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=20_000, pattern=r"\S")
    jurisdiction: Jurisdiction
    effective_on: date
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
