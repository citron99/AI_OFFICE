"""Shared TaskService state: persistence wiring, transitions, publishing and responses."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounting.provider import AccountingProvider
from app.agents.lawyer import LawyerAgent
from app.db.tables.tasks import TaskRecord
from app.integrations.consultant_plus.factory import ConsultantPlusProviderLike
from app.models.agent import AgentResult
from app.models.digest import DIGEST_VERSION, DailyOwnerDigest
from app.models.enums import (
    RiskLevel,
    TaskCategory,
    TaskState,
)
from app.models.legal import LegalResult
from app.models.office import OfficeResult
from app.models.task import TaskCreate, TaskResponse
from app.orchestrator.contracts import RunBudget, RunUsage
from app.orchestrator.processes import process_from_snapshot
from app.orchestrator.service import Orchestrator
from app.orchestrator.state_machine import validate_transition
from app.repositories.tasks import TaskRepository
from app.services.approvals import audit


class TaskServiceCore:
    def __init__(
        self,
        session: AsyncSession,
        orchestrator: Orchestrator,
        accounting_provider: AccountingProvider | None = None,
        lawyer: LawyerAgent | None = None,
        consultant: ConsultantPlusProviderLike | None = None,
    ) -> None:
        self.session = session
        self.repository = TaskRepository(session)
        self.orchestrator = orchestrator
        self.accounting_provider = accounting_provider
        self.lawyer = lawyer
        self.consultant = consultant

    async def _transition(self, task: TaskRecord, target: TaskState) -> None:
        validate_transition(TaskState(task.state), target)
        await self.repository.update_state(task, target)
        await self.session.flush()

    @staticmethod
    def to_response(task: TaskRecord) -> TaskResponse:
        result: AgentResult | None = None
        if task.result:
            result = (
                OfficeResult.model_validate(task.result)
                if task.result.get("mode") == "office_mock_v1"
                else DailyOwnerDigest.model_validate(task.result)
                if task.result.get("mode") == DIGEST_VERSION
                else LegalResult.model_validate(task.result)
                if task.result.get("mode") in {"legal_retrieval_pilot", "legal_analysis_pilot"}
                else AgentResult.model_validate(task.result)
            )
        return TaskResponse(
            task_id=task.id,
            state=TaskState(task.state),
            category=TaskCategory(task.category) if task.category else None,
            risk_level=RiskLevel(task.risk_level) if task.risk_level else None,
            created_at=task.created_at,
            updated_at=task.updated_at,
            completed_at=task.completed_at,
            result=result,
            process=process_from_snapshot(task.process_snapshot) if task.process_snapshot else None,
            run_budget=RunBudget.model_validate(task.run_budget_snapshot)
            if task.run_budget_snapshot
            else None,
            run_usage=RunUsage.model_validate(task.run_usage or {})
            if task.run_budget_snapshot
            else None,
            rework_parent_task_id=task.rework_parent_task_id,
            rework_target_node_ids=task.rework_target_node_ids,
            rework_cycle=task.rework_cycle,
        )

    async def _publish_failed(self, task: TaskRecord) -> None:
        # A timeout can happen after delivery: never overwrite a worker's claimed state.
        await self.session.execute(
            update(TaskRecord)
            .where(TaskRecord.id == task.id, TaskRecord.state == "queued")
            .values(state="failed", completed_at=datetime.now(UTC), updated_at=datetime.now(UTC))
            .execution_options(synchronize_session=False)
        )
        await self.session.refresh(task)
        audit(self.session, task, "queue_publish_failed", {"observed_state": task.state})
        await self.session.commit()

    async def _execute(
        self,
        payload: TaskCreate,
        *,
        user_id: str,
        existing_task: TaskRecord | None = None,
        idempotency_key: str | None = None,
        company_id: str,
    ) -> TaskResponse:
        raise NotImplementedError

    async def _verify_attachments(
        self, attachment_ids: list[str], *, user_id: str, company_id: str
    ) -> None:
        raise NotImplementedError

    async def _publish_for_execution(self, task: TaskRecord) -> TaskResponse:
        """Hand a committed queued task to the worker; fail closed on publish errors."""
        from app.jobs import publish

        try:
            await asyncio.to_thread(publish, task.id)
        except Exception:
            await self._publish_failed(task)
        return self.to_response(task)
