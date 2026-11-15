"""Task lifecycle: submission, queueing, retry, clarification, reads and cancellation."""

import asyncio
import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.exceptions import (
    InvalidStateTransitionError,
    TaskNotFoundError,
)
from app.db.tables.approvals import ApprovalRecord
from app.db.tables.reviews import ResultReviewRecord
from app.db.tables.tasks import TaskRecord
from app.models.enums import (
    TaskState,
)
from app.models.office import OfficeResult
from app.models.process import ProcessGraph
from app.models.task import LegalClarification, TaskCreate, TaskResponse
from app.orchestrator.processes import process_from_snapshot
from app.services.approvals import audit
from app.services.process_graph import build_process_graph
from app.services.task_core import TaskServiceCore


class TaskLifecycleMixin(TaskServiceCore):
    async def create_and_execute(
        self,
        payload: TaskCreate,
        *,
        user_id: str,
        idempotency_key: str | None = None,
        company_id: str,
    ) -> TaskResponse:
        return await self._execute(
            payload,
            user_id=user_id,
            idempotency_key=idempotency_key,
            company_id=company_id,
        )

    async def enqueue(
        self,
        payload: TaskCreate,
        *,
        user_id: str,
        idempotency_key: str | None = None,
        company_id: str,
    ) -> TaskResponse:
        from app.jobs import publish

        await self._verify_attachments(
            payload.attachment_ids, user_id=user_id, company_id=company_id
        )
        task, created = await self.repository.create_once(
            user_id=user_id,
            payload=payload,
            key=idempotency_key,
            company_id=company_id,
        )
        if not created:
            return self.to_response(task)
        audit(self.session, task, "task_queued", {"execution": "celery"})
        await self.session.commit()
        try:
            await asyncio.to_thread(publish, task.id)
        except Exception:
            await self._publish_failed(task)
        return self.to_response(task)

    async def retry(
        self,
        task_id: str,
        *,
        user_id: str,
        queued: bool,
        idempotency_key: str | None = None,
        company_id: str,
    ) -> TaskResponse:
        retry_key = (
            "retry_" + hashlib.sha256(f"{task_id}\0{idempotency_key}".encode()).hexdigest()
            if idempotency_key
            else None
        )
        task = (
            await self.repository.get_for_update(task_id)
            if retry_key
            else await self.repository.get(task_id)
        )
        if task is None or task.user_id != user_id or task.company_id != company_id:
            raise TaskNotFoundError(task_id)
        if task.state == TaskState.FAILED_SAFE.value:
            # TZ TASK-008/REL-008: a safely stopped run resumes in place from
            # its last confirmed checkpoint instead of repeating completed nodes.
            await self.repository.update_state(task, TaskState.QUEUED)
            audit(self.session, task, "task_retry_from_checkpoint", {})
            await self.session.commit()
            if queued:
                return await self._publish_for_execution(task)
            return await self._execute(
                TaskCreate.model_validate(task.request_data),
                user_id=user_id,
                company_id=company_id,
                existing_task=task,
            )
        if task.state != "failed":
            raise InvalidStateTransitionError(task.state, "retry")
        if retry_key:
            existing = await self.repository.get_by_idempotency_key(company_id, retry_key)
            if existing is not None:
                await self.session.commit()
                return self.to_response(existing)
        # New identity and fresh approvals; original evidence/history stays immutable.
        request = TaskCreate.model_validate(task.request_data)
        response = (
            await self.enqueue(
                request,
                user_id=user_id,
                idempotency_key=retry_key,
                company_id=company_id,
            )
            if queued
            else await self.create_and_execute(
                request,
                user_id=user_id,
                idempotency_key=retry_key,
                company_id=company_id,
            )
        )
        audit(self.session, task, "task_retried", {"new_task_id": response.task_id})
        await self.session.commit()
        return response

    async def clarify(
        self,
        task_id: str,
        payload: LegalClarification,
        *,
        user_id: str,
        queued: bool = False,
        company_id: str,
    ) -> TaskResponse:
        task = await self.repository.get(task_id)
        if task is None or task.user_id != user_id or task.company_id != company_id:
            raise TaskNotFoundError(task_id)
        if task.state != TaskState.WAITING_INPUT.value:
            raise InvalidStateTransitionError(task.state, TaskState.QUEUED.value)
        await self._transition(task, TaskState.QUEUED)
        task.result = None
        # Merge into the stored request: rebuilding TaskCreate field by field
        # silently dropped process_id and would drop any future field too.
        request = TaskCreate.model_validate(
            {
                **task.request_data,
                "jurisdiction": payload.jurisdiction,
                "effective_on": payload.effective_on,
            }
        )
        task.request_data = request.model_dump(mode="json")
        if queued:
            await self.session.commit()
            return await self._publish_for_execution(task)
        return await self._execute(
            request,
            user_id=user_id,
            company_id=company_id,
            existing_task=task,
        )

    async def get(self, task_id: str, *, user_id: str, company_id: str) -> TaskResponse:
        task = await self.repository.get(task_id)
        if task is None or task.user_id != user_id or task.company_id != company_id:
            raise TaskNotFoundError(task_id)
        return self.to_response(task)

    async def get_process_graph(
        self,
        task_id: str,
        *,
        user_id: str,
        company_id: str,
    ) -> ProcessGraph:
        task = await self.repository.get(task_id)
        if task is None or task.user_id != user_id or task.company_id != company_id:
            raise TaskNotFoundError(task_id)
        review = await self.session.scalar(
            select(ResultReviewRecord.id).where(ResultReviewRecord.task_id == task_id)
        )
        return build_process_graph(
            task_id=task.id,
            process=process_from_snapshot(task.process_snapshot) if task.process_snapshot else None,
            steps=await self.repository.list_steps(task_id),
            review_eligible=task.state == TaskState.COMPLETED.value and bool(task.result),
            reviewed=review is not None,
        )

    async def cancel(self, task_id: str, *, user_id: str, company_id: str) -> TaskResponse:
        # Same lock order as approval/expiry: task first, approval second.
        task = await self.session.scalar(
            select(TaskRecord)
            .where(
                TaskRecord.id == task_id,
                TaskRecord.user_id == user_id,
                TaskRecord.company_id == company_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if task is None or task.user_id != user_id:
            raise TaskNotFoundError(task_id)
        if task.state == TaskState.CANCELLED.value:
            return self.to_response(task)
        await self._transition(task, TaskState.CANCELLED)
        approval = await self.session.scalar(
            select(ApprovalRecord)
            .where(ApprovalRecord.task_id == task_id, ApprovalRecord.owner_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if approval is not None and approval.status == "pending":
            approval.status = "cancelled"
            approval.decided_at = datetime.now(UTC)
            audit(self.session, task, "approval_cancelled", {"approval_id": approval.id})
        if task.result and task.result.get("mode") == "office_mock_v1":
            result = OfficeResult.model_validate(task.result)
            result.requires_approval = False
            result.status = "task_cancelled"
            result.summary = "Задача отменена. Согласование закрыто; черновик не создан."
            task.result = result.model_dump(mode="json")
        audit(self.session, task, "task_cancelled", {})
        for step in await self.repository.list_steps(task_id):
            if step.state in {TaskState.RUNNING.value, TaskState.QUEUED.value}:
                step.state = TaskState.CANCELLED.value
                step.completed_at = datetime.now(UTC)
        await self.session.commit()
        return self.to_response(task)
