"""Legal provider endpoints: Consultant+ status and the licensed search surface."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.auth import PrincipalDependency, ReviewerDependency, WriterDependency
from app.api.dependencies import SessionDependency
from app.db.tables.consultant_plus import ConsultantPlusSearchEventRecord
from app.models.legal_change import (
    LegalChangeRadarCreate,
    LegalChangeRadarRunResponse,
    LegalChangeReviewCreate,
)
from app.services.legal_change_radar import LegalChangeRadarService
from app.services.licensed_search import guarded_licensed_search

router = APIRouter(prefix="/legal", tags=["legal provider (Consultant+)"])


def radar_service(session: SessionDependency, request: Request) -> LegalChangeRadarService:
    return LegalChangeRadarService(session, request.app.state.consultant_provider)


class LegalSearchRequest(BaseModel):
    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "query": "срок хранения первичных документов по НДС",
                    "jurisdiction": "RU",
                    "effective_on": "2026-01-01",
                }
            ]
        },
    }

    query: str = Field(
        min_length=3,
        max_length=2000,
        description=(
            "Free text sent to the licensed provider via the egress gateway. "
            "DLP-classified RESTRICTED payloads are refused before the "
            "crossing and the decision is journalled."
        ),
        examples=["срок хранения первичных документов по НДС"],
    )
    jurisdiction: str = Field(
        min_length=2,
        max_length=8,
        description="ISO-3166 alpha-2 code of the legal system to search.",
        examples=["RU"],
    )
    effective_on: date = Field(
        description="Point in time at which the answer must be valid.",
        examples=["2026-01-01"],
    )


@router.get("/provider-status")
async def provider_status(
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
) -> dict[str, object]:
    """Health, mode and license scope without exposing any licensed text."""
    provider = request.app.state.consultant_provider
    health = provider.healthcheck()
    scope = provider.license_scope()
    # Tenant-scoped: an unfiltered count() leaks the whole platform's
    # Consultant+ query volume to any authenticated principal and violates
    # the AGENTS.md invariant that every company_id boundary is enforced.
    events_total = await session.scalar(
        select(func.count())
        .select_from(ConsultantPlusSearchEventRecord)
        .where(ConsultantPlusSearchEventRecord.company_id == principal.company_id)
    )
    return {
        "mode": provider.mode,
        "status": health.status,
        "detail": health.detail,
        "license_scope": scope.model_dump(mode="json") if scope else None,
        "recorded_search_events": int(events_total or 0),
    }


@router.post("/search")
async def search(
    payload: LegalSearchRequest,
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, object]:
    """Manual licensed search through the egress gate; every crossing is journalled."""
    results = await guarded_licensed_search(
        session,
        request.app.state.consultant_provider,
        query=payload.query,
        jurisdiction=payload.jurisdiction,
        effective_on=payload.effective_on,
        company_id=principal.company_id,
        owner_id=principal.user_id,
        channel="manual_search",
        limit=limit,
    )
    return {
        "query_id": results[0].query_id if results else None,
        "results": [item.model_dump(mode="json") for item in results],
    }


@router.get("/change-radar/runs", response_model=list[LegalChangeRadarRunResponse])
async def list_change_radar_runs(
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
) -> list[LegalChangeRadarRunResponse]:
    return await radar_service(session, request).list_runs(
        owner_id=principal.user_id, company_id=principal.company_id
    )


@router.post(
    "/change-radar/runs",
    response_model=LegalChangeRadarRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_change_radar_run(
    payload: LegalChangeRadarCreate,
    principal: WriterDependency,
    session: SessionDependency,
    request: Request,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ],
) -> LegalChangeRadarRunResponse:
    return await radar_service(session, request).create(
        payload,
        owner_id=principal.user_id,
        company_id=principal.company_id,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/change-radar/runs/{run_id}/review",
    response_model=LegalChangeRadarRunResponse,
)
async def review_change_radar_run(
    run_id: str,
    payload: LegalChangeReviewCreate,
    principal: ReviewerDependency,
    session: SessionDependency,
    request: Request,
) -> LegalChangeRadarRunResponse:
    if principal.role not in {"owner", "lawyer"}:
        raise HTTPException(403, "Owner or lawyer role required for legal change review")
    return await radar_service(session, request).review(
        run_id,
        payload,
        reviewer_id=principal.user_id,
        company_id=principal.company_id,
    )
