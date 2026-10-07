from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounting.provider import AccountingProvider
from app.agents.lawyer import LawyerAgent
from app.api.auth import PrincipalDependency
from app.db.tables.companies import CompanyMembershipRecord, CompanyRecord
from app.services.knowledge import KnowledgeService
from app.services.tasks import TaskService


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_accounting_provider(request: Request) -> AccountingProvider:
    return cast(AccountingProvider, request.app.state.accounting_provider)


AccountingProviderDependency = Annotated[AccountingProvider, Depends(get_accounting_provider)]


async def company_context(
    request: Request, principal: PrincipalDependency, session: SessionDependency
) -> PrincipalDependency:
    """Bootstrap only the server-configured demo/API-key principals.

    Session principals are checked on every request in current_principal and
    must never recreate a missing or disabled membership here.
    """

    if request.app.state.settings.auth_mode in {"token", "oidc"}:
        return principal

    try:
        company = await session.get(CompanyRecord, principal.company_id)
        if company is None:
            session.add(CompanyRecord(id=principal.company_id, name="Demo Investment Company"))
            # Flush the company first: the membership has no ORM relationship,
            # so the unit of work cannot order these inserts by itself.
            await session.flush()
            if await session.get(CompanyRecord, principal.company_id) is None:
                # Lost the bootstrap race: a concurrent request committed it.
                await session.rollback()
        membership = await session.scalar(
            select(CompanyMembershipRecord).where(
                CompanyMembershipRecord.company_id == principal.company_id,
                CompanyMembershipRecord.user_id == principal.user_id,
            )
        )
        if membership is None:
            session.add(
                CompanyMembershipRecord(
                    company_id=principal.company_id,
                    user_id=principal.user_id,
                    role=principal.role if principal.role != "service" else "member",
                )
            )
        await session.commit()
    except IntegrityError:
        # A concurrent request bootstrapped the same company or membership.
        await session.rollback()
    return principal


CompanyContextDependency = Annotated[PrincipalDependency, Depends(company_context)]


def get_task_service(
    request: Request, session: SessionDependency, principal: CompanyContextDependency
) -> TaskService:
    return TaskService(
        session,
        request.app.state.orchestrator,
        request.app.state.accounting_provider,
        LawyerAgent(
            KnowledgeService(
                session, request.app.state.settings, request.app.state.embedding_provider
            ),
            request.app.state.llm_provider
            if request.app.state.settings.legal_analysis_enabled
            else None,
            consultant=request.app.state.consultant_provider,
        ),
        consultant=request.app.state.consultant_provider,
    )


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]
