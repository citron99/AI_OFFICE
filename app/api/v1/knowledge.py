from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.auth import PrincipalDependency, WriterDependency
from app.api.dependencies import SessionDependency
from app.db.tables.knowledge import KnowledgeSourceRecord
from app.models.knowledge import SearchRequest, SearchResponse, SourceCreate, SourceResponse
from app.services.knowledge import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["legal knowledge (local pilot)"])


@router.get("/sources", response_model=list[SourceResponse])
async def list_sources(
    session: SessionDependency,
    principal: PrincipalDependency,
) -> list[SourceResponse]:
    sources = await session.scalars(
        select(KnowledgeSourceRecord)
        .where(
            KnowledgeSourceRecord.owner_id == principal.user_id,
            KnowledgeSourceRecord.company_id == principal.company_id,
        )
        .order_by(KnowledgeSourceRecord.id)
        .limit(100)
    )
    return [SourceResponse.model_validate(source) for source in sources]


@router.post("/sources", response_model=SourceResponse, status_code=201)
async def ingest_source(
    payload: SourceCreate,
    request: Request,
    session: SessionDependency,
    principal: WriterDependency,
) -> SourceResponse:
    return await KnowledgeService(
        session, request.app.state.settings, request.app.state.embedding_provider
    ).ingest(
        payload,
        owner_id=principal.user_id,
        company_id=principal.company_id,
    )


@router.post("/search", response_model=SearchResponse)
async def search_sources(
    payload: SearchRequest,
    request: Request,
    session: SessionDependency,
    principal: PrincipalDependency,
) -> SearchResponse:
    return await KnowledgeService(
        session, request.app.state.settings, request.app.state.embedding_provider
    ).search(
        payload,
        owner_id=principal.user_id,
        company_id=principal.company_id,
    )


@router.post("/sources/{source_id}/reindex", response_model=SourceResponse)
async def reindex_source(
    source_id: str, request: Request, session: SessionDependency, principal: WriterDependency
) -> SourceResponse:
    return await KnowledgeService(
        session, request.app.state.settings, request.app.state.embedding_provider
    ).reindex(
        source_id,
        owner_id=principal.user_id,
        company_id=principal.company_id,
    )
