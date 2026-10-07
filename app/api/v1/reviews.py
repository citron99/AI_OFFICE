from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import BusinessOwnerDependency, PrincipalDependency, ReviewerDependency
from app.api.dependencies import SessionDependency, TaskServiceDependency
from app.core.exceptions import RunBudgetExceededError
from app.core.security import redact
from app.db.tables.reviews import ResultReviewRecord
from app.db.tables.tasks import TaskRecord, TaskStepRecord
from app.models.enums import TaskState
from app.models.process import (
    ProcessControlReport,
    ProcessDefinition,
    ProcessQualityReport,
    ResultReviewCreate,
)
from app.orchestrator.contracts import ProcessDefinitionV2
from app.orchestrator.passport import ProcessDefinitionV3, available_passports, passport_for
from app.orchestrator.processes import (
    daily_cash_and_receivable_risk_process,
    office_process_v2,
    process_from_snapshot,
)
from app.services.approvals import audit, payload_hash
from app.services.contour_state import ProcessRuntimeUpdate, get_runtime, update_runtime

router = APIRouter(tags=["processes and result reviews"])


def review_data(record: ResultReviewRecord) -> dict[str, Any]:
    created_at = _as_utc(record.created_at)
    return {
        "id": record.id,
        "task_id": record.task_id,
        "reviewer_id": record.reviewer_id,
        "decision": record.decision,
        "reason": record.reason,
        "result_hash": record.result_hash,
        "target_node_ids": record.target_node_ids,
        "rework_task_id": record.rework_task_id,
        "created_at": created_at,
    }


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


ResponseModels = list[ProcessDefinition | ProcessDefinitionV2 | ProcessDefinitionV3]


@router.get("/processes", response_model=ResponseModels)
async def processes(
    principal: PrincipalDependency,
) -> list[ProcessDefinitionV2 | ProcessDefinitionV3]:
    return [
        office_process_v2(principal.user_id),
        daily_cash_and_receivable_risk_process(principal.user_id),
        *available_passports(),
    ]


@router.get("/processes/{process_id}/runtime")
async def get_process_runtime(
    process_id: str,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> dict[str, Any]:
    """Autonomy ladder position and kill switches for one process."""
    state = await get_runtime(session, company_id=principal.company_id, process_id=process_id)
    return state.model_dump(mode="json")


@router.post("/processes/{process_id}/runtime")
async def set_process_runtime(
    process_id: str,
    payload: ProcessRuntimeUpdate,
    principal: BusinessOwnerDependency,
    session: SessionDependency,
) -> dict[str, Any]:
    """Only the OWNER moves the ladder or flips a kill switch, instantly."""
    # TZ 7.1: autonomy may only rise on measured quality; the passport
    # ceiling can never be exceeded through the runtime API.
    passport = passport_for(process_id)
    if passport is not None and payload.autonomy_level is not None:
        if not passport.allows_autonomy(payload.autonomy_level):
            raise HTTPException(
                409,
                f"Autonomy level {payload.autonomy_level} exceeds the passport "
                f"ceiling {passport.autonomy_level} for {process_id}",
            )
    # Who changed what is persisted immutably on the runtime row itself
    # (updated_by/updated_at), so no task-anchored audit event is needed.
    state = await update_runtime(
        session,
        company_id=principal.company_id,
        process_id=process_id,
        update=payload,
        updated_by=principal.user_id,
    )
    return state.model_dump(mode="json")


@router.get("/processes/quality", response_model=ProcessQualityReport)
async def process_quality(
    principal: PrincipalDependency,
    session: SessionDependency,
    days: int = Query(default=30, ge=1, le=90),
) -> ProcessQualityReport:
    window_started = datetime.now(UTC) - timedelta(days=days)
    tasks = list(
        (
            await session.scalars(
                select(TaskRecord).where(
                    TaskRecord.user_id == principal.user_id,
                    TaskRecord.company_id == principal.company_id,
                    TaskRecord.state == TaskState.COMPLETED.value,
                    TaskRecord.completed_at >= window_started,
                    TaskRecord.process_snapshot.is_not(None),
                    TaskRecord.result.is_not(None),
                )
            )
        ).all()
    )
    task_by_id = {task.id: task for task in tasks}
    reviews: list[ResultReviewRecord] = []
    if task_by_id:
        reviews = list(
            (
                await session.scalars(
                    select(ResultReviewRecord).where(ResultReviewRecord.task_id.in_(task_by_id))
                )
            ).all()
        )
    decisions = dict.fromkeys(["accepted", "rework_required", "rejected"], 0)
    latencies: list[float] = []
    for review in reviews:
        decisions[review.decision] += 1
        completed_at = task_by_id[review.task_id].completed_at
        if completed_at is not None:
            latencies.append(
                max(0, (_as_utc(review.created_at) - _as_utc(completed_at)).total_seconds())
            )
    completed_tasks = len(tasks)
    reviewed_results = len(reviews)
    return ProcessQualityReport(
        window_started=window_started,
        completed_tasks=completed_tasks,
        reviewed_results=reviewed_results,
        pending_reviews=completed_tasks - reviewed_results,
        review_rate=reviewed_results / completed_tasks if completed_tasks else 0,
        decisions=decisions,
        average_review_seconds=round(sum(latencies) / len(latencies)) if latencies else None,
    )


@router.get("/processes/controls", response_model=ProcessControlReport)
async def process_controls(
    principal: PrincipalDependency,
    session: SessionDependency,
    days: int = Query(default=30, ge=1, le=90),
) -> ProcessControlReport:
    """Summarize policy and postflight controls without returning task contents."""
    window_started = datetime.now(UTC) - timedelta(days=days)
    tasks = list(
        (
            await session.scalars(
                select(TaskRecord).where(
                    TaskRecord.user_id == principal.user_id,
                    TaskRecord.company_id == principal.company_id,
                    TaskRecord.state == TaskState.COMPLETED.value,
                    TaskRecord.result.is_not(None),
                )
            )
        ).all()
    )
    office_results = [
        task.result
        for task in tasks
        if isinstance(task.result, dict) and "policy_decision" in task.result
    ]
    decisions = dict.fromkeys(
        [
            "allow_read",
            "allow_draft",
            "require_owner_approval",
            "deny",
            "escalate",
            "owner_only_outside_agent",
        ],
        0,
    )
    legacy_decision_map = {"allow": "allow_read", "require_approval": "require_owner_approval"}
    flags: Counter[str] = Counter()
    postflight_completed = 0
    for result in office_results:
        decision = result.get("policy_decision")
        if not isinstance(decision, str):
            continue
        decision = legacy_decision_map.get(decision, decision)
        if decision in decisions:
            decisions[decision] += 1
        security = result.get("security")
        if isinstance(security, dict) and security.get("status") == "security_postflight_report":
            postflight_completed += 1
            raw_flags = security.get("control_flags", [])
            if isinstance(raw_flags, list):
                flags.update(flag for flag in raw_flags if isinstance(flag, str))
    count = len(office_results)
    return ProcessControlReport(
        window_started=window_started,
        office_results=count,
        postflight_completed=postflight_completed,
        postflight_coverage=postflight_completed / count if count else 0,
        policy_decisions=decisions,
        control_flags=dict(sorted(flags.items())),
    )


@router.get("/tasks/{task_id}/result-review")
async def get_review(
    task_id: str,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> dict[str, Any]:
    task = await session.scalar(
        select(TaskRecord).where(
            TaskRecord.id == task_id,
            TaskRecord.user_id == principal.user_id,
            TaskRecord.company_id == principal.company_id,
        )
    )
    if task is None:
        raise HTTPException(404, "Task not found")
    record = await session.scalar(
        select(ResultReviewRecord).where(ResultReviewRecord.task_id == task_id)
    )
    return {
        "process": task.process_snapshot,
        "result_hash": payload_hash(task.result) if task.result else None,
        "eligible": (
            task.state == "completed" and bool(task.result) and bool(task.process_snapshot)
        ),
        "review": review_data(record) if record else None,
    }


@router.post("/tasks/{task_id}/result-review")
async def submit_review(
    task_id: str,
    payload: ResultReviewCreate,
    principal: ReviewerDependency,
    session: SessionDependency,
    service: TaskServiceDependency,
) -> dict[str, Any]:
    task = await session.scalar(
        select(TaskRecord)
        .where(
            TaskRecord.id == task_id,
            TaskRecord.user_id == principal.user_id,
            TaskRecord.company_id == principal.company_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise HTTPException(404, "Task not found")
    if task.state != "completed" or not task.result or not task.process_snapshot:
        raise HTTPException(409, "Result is not eligible for review")
    contract = process_from_snapshot(task.process_snapshot)
    if (
        contract.result_owner_id != principal.user_id
        or principal.role not in contract.reviewer_roles
    ):
        raise HTTPException(403, "Reviewer is not authorized by the process")
    if payload.result_hash != payload_hash(task.result):
        raise HTTPException(409, "Result changed; reload before reviewing")
    available_nodes = {
        node_id
        for node_id in await session.scalars(
            select(TaskStepRecord.node_id).where(
                TaskStepRecord.task_id == task_id,
                TaskStepRecord.node_id.is_not(None),
            )
        )
    }
    if set(payload.target_node_ids) - available_nodes:
        raise HTTPException(422, "Rework target is not a node of this task")
    reason = redact(payload.reason.strip())
    query = select(ResultReviewRecord).where(ResultReviewRecord.task_id == task_id)
    existing = await session.scalar(query)
    if existing:
        if (
            existing.decision,
            existing.reason,
            existing.result_hash,
            existing.target_node_ids,
        ) != (
            payload.decision,
            reason,
            payload.result_hash,
            payload.target_node_ids,
        ):
            raise HTTPException(409, "Review is immutable")
        return review_data(existing)
    record = ResultReviewRecord(
        company_id=principal.company_id,
        task_id=task_id,
        reviewer_id=principal.user_id,
        decision=payload.decision,
        reason=reason,
        result_hash=payload.result_hash,
        target_node_ids=payload.target_node_ids,
    )
    session.add(record)
    audit(
        session,
        task,
        "result_reviewed",
        {
            "decision": payload.decision,
            "result_hash": payload.result_hash,
        },
    )
    try:
        if payload.decision == "rework_required":
            rework = await service.create_rework(
                task,
                target_node_ids=payload.target_node_ids,
                user_id=principal.user_id,
                company_id=principal.company_id,
            )
            record.rework_task_id = rework.task_id
            await session.commit()
        else:
            await session.commit()
    except IntegrityError:
        await session.rollback()
        winner = await session.scalar(query)
        if winner and (
            winner.decision,
            winner.reason,
            winner.result_hash,
            winner.target_node_ids,
        ) == (
            payload.decision,
            reason,
            payload.result_hash,
            payload.target_node_ids,
        ):
            return review_data(winner)
        raise HTTPException(409, "Review is immutable") from None
    except (RunBudgetExceededError, ValueError) as error:
        await session.rollback()
        raise HTTPException(409, str(error)) from None
    return review_data(record)
