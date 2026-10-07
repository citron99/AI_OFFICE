import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IdempotencyConflictError, InvalidStateTransitionError
from app.core.ids import new_id
from app.core.security import redact, redact_payload
from app.db.tables.agent_runs import AgentRunRecord
from app.db.tables.tasks import TaskRecord, TaskStepRecord
from app.db.tables.users import UserRecord
from app.models.enums import RiskLevel, TaskCategory, TaskState
from app.models.task import TaskCreate, TaskStepPlan
from app.orchestrator.processes import process_for_task


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: str,
        payload: TaskCreate,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        company_id: str,
    ) -> TaskRecord:
        user = await self.session.get(UserRecord, user_id)
        if user is None:
            try:
                async with self.session.begin_nested():
                    self.session.add(
                        UserRecord(
                            id=user_id,
                            email=f"{user_id}@demo.invalid",
                            display_name="Demo Owner",
                            role="owner",
                            status="active",
                        )
                    )
                    await self.session.flush()
            except IntegrityError:
                if await self.session.get(UserRecord, user_id) is None:
                    raise
        process = process_for_task(payload.process_id, user_id)
        task = TaskRecord(
            company_id=company_id,
            user_id=user_id,
            state=TaskState.QUEUED.value,
            input_text=redact(payload.message),
            attachment_ids=payload.attachment_ids,
            requested_agent=payload.requested_agent.value if payload.requested_agent else None,
            request_data={**payload.model_dump(mode="json"), "message": redact(payload.message)},
            trace_id=new_id("trace"),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            process_snapshot=process.model_dump(mode="json"),
            run_budget_snapshot=process.run_budget.model_dump(mode="json"),
            run_usage={},
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def create_once(
        self,
        *,
        user_id: str,
        payload: TaskCreate,
        key: str | None,
        company_id: str,
    ) -> tuple[TaskRecord, bool]:
        if key is None:
            return (
                await self.create(user_id=user_id, payload=payload, company_id=company_id),
                True,
            )
        fingerprint = hashlib.sha256(
            json.dumps(
                payload.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        # TZ TASK-002: idempotency scope is the company, not the user.
        query = select(TaskRecord).where(
            TaskRecord.company_id == company_id, TaskRecord.idempotency_key == key
        )
        task = await self.session.scalar(query)
        if task is None:
            try:
                async with self.session.begin_nested():
                    task = await self.create(
                        user_id=user_id,
                        payload=payload,
                        idempotency_key=key,
                        request_hash=fingerprint,
                        company_id=company_id,
                    )
                return task, True
            except IntegrityError:
                task = await self.session.scalar(query)
                if task is None:
                    raise
        if task.request_hash != fingerprint:
            raise IdempotencyConflictError()
        return task, False

    async def get(self, task_id: str) -> TaskRecord | None:
        return await self.session.get(TaskRecord, task_id)

    async def get_for_update(self, task_id: str) -> TaskRecord | None:
        records = await self.session.scalars(
            select(TaskRecord)
            .where(TaskRecord.id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return records.first()

    async def get_by_idempotency_key(self, company_id: str, key: str) -> TaskRecord | None:
        records = await self.session.scalars(
            select(TaskRecord).where(
                TaskRecord.company_id == company_id,
                TaskRecord.idempotency_key == key,
            )
        )
        return records.first()

    async def update_state(self, task: TaskRecord, state: TaskState) -> None:
        expected_state = task.state
        result = await self.session.execute(
            update(TaskRecord)
            .where(TaskRecord.id == task.id, TaskRecord.state == expected_state)
            .values(state=state.value)
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise InvalidStateTransitionError(expected_state, state.value)
        task.state = state.value
        task.updated_at = datetime.now(UTC)
        if state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
            task.completed_at = datetime.now(UTC)
        await self.session.flush()

    async def set_routing(
        self,
        task: TaskRecord,
        *,
        category: TaskCategory,
        risk_level: RiskLevel,
    ) -> None:
        task.category = category.value
        task.risk_level = risk_level.value
        task.updated_at = datetime.now(UTC)
        await self.session.flush()

    async def set_result(self, task: TaskRecord, result: dict[str, Any]) -> None:
        task.result = result
        task.updated_at = datetime.now(UTC)
        await self.session.flush()

    async def add_step(self, task: TaskRecord, plan: TaskStepPlan) -> TaskStepRecord:
        step = TaskStepRecord(
            id=plan.step_id,
            task_id=task.id,
            agent_type=plan.agent.value,
            action=plan.action,
            node_id=plan.node_id,
            state=TaskState.QUEUED.value,
            depends_on=plan.depends_on,
            input_refs=plan.input_refs,
        )
        self.session.add(step)
        await self.session.flush()
        return step

    async def claim_step(self, task: TaskRecord, step: TaskStepRecord) -> bool:
        """Atomically claim a queued node before an external agent call starts."""

        now = datetime.now(UTC)
        result = await self.session.execute(
            update(TaskStepRecord)
            .where(
                TaskStepRecord.id == step.id,
                TaskStepRecord.task_id == task.id,
                TaskStepRecord.state == TaskState.QUEUED.value,
            )
            .values(
                state=TaskState.RUNNING.value,
                started_at=now,
                attempt=TaskStepRecord.attempt + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            return False
        step.state = TaskState.RUNNING.value
        step.started_at = now
        step.attempt += 1
        await self.session.flush()
        return True

    async def list_steps(self, task_id: str) -> list[TaskStepRecord]:
        result = await self.session.execute(
            select(TaskStepRecord)
            .where(TaskStepRecord.task_id == task_id)
            .order_by(TaskStepRecord.id)
        )
        return list(result.scalars())

    async def save_agent_run(
        self,
        *,
        task_id: str,
        step_id: str,
        agent_type: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        latency_ms: int,
        prompt_version: str = "dummy-v1",
        model_id: str = "mock",
    ) -> AgentRunRecord:
        record = AgentRunRecord(
            task_id=task_id,
            step_id=step_id,
            agent_type=agent_type,
            input=redact_payload(input_data),
            output=redact_payload(output_data),
            status="completed",
            latency_ms=latency_ms,
            prompt_version=prompt_version,
            model_id=model_id,
        )
        self.session.add(record)
        await self.session.flush()
        return record
