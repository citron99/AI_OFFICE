"""Legal provider endpoints: Consultant+ status and the licensed search surface."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.auth import PrincipalDependency, ReviewerDependency, WriterDependency
from app.api.dependencies import SessionDependency
from app.db.tables.consultant_plus import ConsultantPlusSearchEventRecord
from app.integrations.consultant_plus.exceptions import (
    ConsultantPlusUnavailableError,
    LicenseScopeExceededError,
)
from app.models.legal_change import (
    LegalChangeRadarCreate,
    LegalChangeRadarRunResponse,
    LegalChangeReviewCreate,
)
from app.services.legal_change_radar import LegalChangeRadarService

router = APIRouter(prefix="/legal", tags=["legal provider (Consultant+)"])


def radar_service(session: SessionDependency, request: Request) -> LegalChangeRadarService:
    return LegalChangeRadarService(session, request.app.state.consultant_provider)


class LegalSearchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=3, max_length=2000)
    jurisdiction: str = Field(min_length=2, max_length=8)
    effective_on: date


@router.get("/provider-status")
async def provider_status(
    principal: PrincipalDependency,
    session: SessionDependency,
    request: Request,
) -> dict[str, object]:
    """Health, mode and license scope without exposing any licensed text."""
    del principal
    provider = request.app.state.consultant_provider
    health = provider.healthcheck()
    scope = provider.license_scope()
    events_total = await session.scalar(
        select(func.count()).select_from(ConsultantPlusSearchEventRecord)
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
    request: Request,
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, object]:
    """Manual licensed search; a full route always records its trail in the task."""
    del principal
    provider = request.app.state.consultant_provider
    try:
        results = provider.search(
            query=payload.query,
            jurisdiction=payload.jurisdiction,
            effective_on=payload.effective_on,
            limit=limit,
        )
    except ConsultantPlusUnavailableError as error:
        raise HTTPException(503, str(error)) from None
    except LicenseScopeExceededError as error:
        raise HTTPException(403, str(error)) from None
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
