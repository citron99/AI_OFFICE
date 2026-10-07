from typing import Annotated

from fastapi import APIRouter, Header, Request, status

from app.api.auth import PrincipalDependency, WriterDependency
from app.api.dependencies import TaskServiceDependency
from app.models.enums import AgentType
from app.models.process import ProcessGraph
from app.models.task import DailyControlCreate, LegalClarification, TaskCreate, TaskResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    service: TaskServiceDependency,
    principal: WriterDependency,
    request: Request,
    idempotency_key: Annotated[
        str | None, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ] = None,
) -> TaskResponse:
    if request.app.state.settings.execution_mode == "queue":
        return await service.enqueue(
            payload,
            user_id=principal.user_id,
            idempotency_key=idempotency_key,
            company_id=principal.company_id,
        )
    return await service.create_and_execute(
        payload,
        user_id=principal.user_id,
        idempotency_key=idempotency_key,
        company_id=principal.company_id,
    )


@router.post(
    "/daily-cash-and-receivable-risk",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def run_daily_cash_and_receivable_risk(
    payload: DailyControlCreate,
    service: TaskServiceDependency,
    principal: WriterDependency,
    request: Request,
) -> TaskResponse:
    """Run the first repeatable owner control; it only reads synthetic accounting data."""

    task = TaskCreate(
        message="Ежедневный контроль денежных средств и рисков неплатежей",
        requested_agent=AgentType.ACCOUNTANT,
        effective_on=payload.effective_on,
        process_id="daily_cash_and_receivable_risk",
    )
    if request.app.state.settings.execution_mode == "queue":
        return await service.enqueue(
            task,
            user_id=principal.user_id,
            company_id=principal.company_id,
        )
    return await service.create_and_execute(
        task,
        user_id=principal.user_id,
        company_id=principal.company_id,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    service: TaskServiceDependency,
    principal: PrincipalDependency,
) -> TaskResponse:
    return await service.get(task_id, user_id=principal.user_id, company_id=principal.company_id)


@router.get("/{task_id}/process-graph", response_model=ProcessGraph)
async def get_process_graph(
    task_id: str,
    service: TaskServiceDependency,
    principal: PrincipalDependency,
) -> ProcessGraph:
    return await service.get_process_graph(
        task_id,
        user_id=principal.user_id,
        company_id=principal.company_id,
    )


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: str,
    service: TaskServiceDependency,
    principal: WriterDependency,
) -> TaskResponse:
    return await service.cancel(task_id, user_id=principal.user_id, company_id=principal.company_id)


@router.post("/{task_id}/clarify", response_model=TaskResponse)
async def clarify_task(
    task_id: str,
    payload: LegalClarification,
    service: TaskServiceDependency,
    principal: WriterDependency,
    request: Request,
) -> TaskResponse:
    return await service.clarify(
        task_id,
        payload,
        user_id=principal.user_id,
        queued=request.app.state.settings.execution_mode == "queue",
        company_id=principal.company_id,
    )


@router.post("/{task_id}/retry", response_model=TaskResponse, status_code=201)
async def retry_task(
    task_id: str,
    service: TaskServiceDependency,
    principal: WriterDependency,
    request: Request,
    idempotency_key: Annotated[
        str | None, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ] = None,
) -> TaskResponse:
    return await service.retry(
        task_id,
        user_id=principal.user_id,
        queued=request.app.state.settings.execution_mode == "queue",
        idempotency_key=idempotency_key,
        company_id=principal.company_id,
    )
