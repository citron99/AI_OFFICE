import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.accounting.factory import AccountingProviderFactory
from app.agents.dummy import DummyAgent
from app.api.rate_limit import RateLimitMiddleware
from app.api.router import api_router
from app.config import Settings, get_settings
from app.core.exceptions import (
    ArtifactNotFoundError,
    FileValidationError,
    IdempotencyConflictError,
    InvalidStateTransitionError,
    TaskNotFoundError,
)
from app.db.base import Base
from app.db.session import create_engine, create_session_factory
from app.integrations.consultant_plus.factory import (
    create_consultant_plus_provider,
)
from app.knowledge.embeddings import EmbeddingProvider
from app.knowledge.local_embeddings import create_embedding_provider
from app.llm.base import LLMProvider
from app.llm.factory import create_llm_provider
from app.orchestrator.planner import SimplePlanner
from app.orchestrator.router import KeywordRouter
from app.orchestrator.service import Orchestrator
from app.storage.factory import create_storage


def build_orchestrator() -> Orchestrator:
    return Orchestrator(
        router=KeywordRouter(),
        planner=SimplePlanner(),
        dummy_agent=DummyAgent(),
    )


def create_app(
    *,
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    llm_provider: LLMProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    if resolved_settings.app_env == "production":
        raise RuntimeError("Production is disabled pending security and acceptance review")
    if resolved_settings.auth_mode == "api_key" and not resolved_settings.auth_token_hashes:
        raise RuntimeError("API-key authentication requires configured token hashes")
    if resolved_settings.auth_mode in {"token", "oidc"} and not resolved_settings.session_secret:
        raise RuntimeError("Token and OIDC authentication require SESSION_SECRET")
    if resolved_settings.auth_mode == "oidc" and not resolved_settings.oidc_issuer_url:
        raise RuntimeError("OIDC authentication requires OIDC_ISSUER_URL")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owns_engine = engine is None
        active_engine = engine or create_engine(resolved_settings.database_url)
        active_factory = session_factory or create_session_factory(active_engine)
        application.state.settings = resolved_settings
        application.state.engine = active_engine
        application.state.session_factory = active_factory
        application.state.llm_provider = llm_provider or create_llm_provider(resolved_settings)
        application.state.accounting_provider = AccountingProviderFactory().create(
            resolved_settings
        )
        application.state.consultant_provider = create_consultant_plus_provider(resolved_settings)
        application.state.artifact_storage = create_storage(resolved_settings)
        application.state.orchestrator = build_orchestrator()

        if resolved_settings.auto_create_schema:
            async with active_engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        try:
            application.state.embedding_provider = embedding_provider or await asyncio.to_thread(
                create_embedding_provider, resolved_settings
            )
            yield
        finally:
            await application.state.llm_provider.aclose()
            if owns_engine:
                await active_engine.dispose()

    application = FastAPI(
        title="AI-офис собственника",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        RateLimitMiddleware,
        limit_per_minute=resolved_settings.rate_limit_per_minute,
        enabled=resolved_settings.rate_limit_enabled,
    )
    application.include_router(api_router)

    @application.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(
        request: Request, exc: IdempotencyConflictError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"code": "IDEMPOTENCY_CONFLICT"})

    @application.exception_handler(FileValidationError)
    async def file_validation_handler(request: Request, exc: FileValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"code": "FILE_INVALID", "message": str(exc)})

    @application.exception_handler(ArtifactNotFoundError)
    async def artifact_not_found_handler(
        request: Request, exc: ArtifactNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"code": "ARTIFACT_NOT_FOUND"})

    @application.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready", tags=["health"])
    async def ready(request: Request) -> JSONResponse:
        checks: dict[str, bool] = {"database": False, "llm_provider": False}
        try:
            async with request.app.state.session_factory() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = True
            checks["llm_provider"] = await request.app.state.llm_provider.healthcheck()
        except Exception:
            pass
        if request.app.state.settings.execution_mode == "queue":
            checks["queue_broker"] = False
            try:
                from redis.asyncio import Redis

                async with Redis.from_url(
                    request.app.state.settings.redis_url,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                ) as broker:
                    checks["queue_broker"] = bool(await broker.ping())
            except Exception:
                pass
        code = 200 if all(checks.values()) else 503
        payload: dict[str, Any] = {
            "status": "ready" if code == 200 else "not_ready",
            "checks": checks,
        }
        return JSONResponse(status_code=code, content=payload)

    @application.exception_handler(TaskNotFoundError)
    async def task_not_found_handler(request: Request, exc: TaskNotFoundError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=404,
            content={"code": "TASK_NOT_FOUND", "message": str(exc), "retryable": False},
        )

    @application.exception_handler(InvalidStateTransitionError)
    async def invalid_transition_handler(
        request: Request, exc: InvalidStateTransitionError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=409,
            content={"code": "INVALID_STATE_TRANSITION", "message": str(exc), "retryable": False},
        )

    return application


app = create_app()
