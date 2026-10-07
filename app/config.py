import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["demo", "api_key", "token", "oidc"] = "demo"
    # TZ 10.1 OIDC federation: the IdP asserts identity via its userinfo
    # endpoint; role and company are mapped SERVER-SIDE from claims.
    oidc_issuer_url: str | None = None
    oidc_role_claim: str = "office_role"
    oidc_company_claim: str = "office_company"
    oidc_default_role: str = "auditor"
    # TZ 10.1: production JWT/session secret; required for auth_mode=token,
    # has no default value anywhere.
    session_secret: str | None = Field(default=None, repr=False)
    # SHA-256(token) -> {"user_id": "...", "role": "<TZ V2.1 RBAC role>"}
    auth_token_hashes: dict[str, dict[str, str]] = Field(default_factory=dict, repr=False)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_office"
    redis_url: str = "redis://localhost:6379/0"
    execution_mode: Literal["sync", "queue"] = "sync"
    anthropic_api_key: str | None = Field(default=None, repr=False)
    llm_provider: Literal["anthropic", "mock"] = "mock"
    llm_model: str = "claude-sonnet-4-5"
    accounting_provider: Literal["mock", "onec_file", "onec"] = "mock"
    onec_exchange_dir: str | None = None
    legal_rag_top_k: int = Field(default=5, ge=1, le=50)
    # LEG-007 freshness policy: warn when RAG sources were indexed before
    # the window. 0 disables the policy (pilot default).
    legal_rag_max_source_age_days: int = Field(default=0, ge=0, le=3650)
    embedding_provider: Literal["mock", "local_sentence_transformer"] = "mock"
    embedding_model_path: Path | None = None
    embedding_dimensions: int = Field(default=384, ge=1, le=4096)
    semantic_min_score: float = Field(default=0.3, ge=0, le=1)
    legal_analysis_enabled: bool = False
    legal_analysis_timeout_seconds: float = Field(default=45, gt=0, le=120)
    legal_document_max_chars: int = Field(default=40_000, ge=100, le=100_000)
    # Consultant+ licensed channel: "mock" for the synthetic corpus, "licensed"
    # for the production adapter, "off" stops every legal route in WAITING_SOURCE.
    consultant_plus_mode: Literal["mock", "licensed", "off"] = "mock"
    auto_create_schema: bool = False
    upload_dir: Path = Path("uploads")
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    # TZ 9.2 API gateway: simple per-client sliding-window rate limit.
    rate_limit_per_minute: int = Field(default=600, ge=1, le=100_000)
    rate_limit_enabled: bool = True
    # TZ 9.5 object storage: local directory (pilot default) or S3/MinIO bucket.
    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "ai-office-artifacts"
    s3_access_key: str | None = Field(default=None, repr=False)
    s3_secret_key: str | None = Field(default=None, repr=False)
    # ART-003: uploaded artifacts carry a retention deadline.
    artifact_retention_days: int = Field(default=365, ge=1, le=3650)

    @field_validator("auth_token_hashes")
    @classmethod
    def validate_principals(cls, values: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        for digest, principal in values.items():
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Authentication keys must be SHA-256 hex digests")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", principal.get("user_id", "")):
                raise ValueError("Invalid principal user_id")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", principal.get("company_id", "comp_demo")):
                raise ValueError("Invalid principal company_id")
            if principal.get("role") not in {
                "owner",
                "admin",
                "auditor",
                "accountant",
                "lawyer",
                "security",
                "service",
            }:
                raise ValueError("Invalid principal role")
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
