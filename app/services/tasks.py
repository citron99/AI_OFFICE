import asyncio
import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounting.digest import build_daily_digest
from app.accounting.provider import AccountingProvider
from app.agents.lawyer import LawyerAgent
from app.agents.principals import issue_capability_grants, machine_identity_for, principal_for
from app.agents.security import SecurityAgent
from app.core.exceptions import (
    ArtifactNotFoundError,
    InvalidStateTransitionError,
    ModelOutputInvalidError,
    NodeExecutionFailed,
    RunBudgetExceededError,
    TaskNotFoundError,
)
from app.core.ids import new_id
from app.core.policy import POLICY_VERSION, decide
from app.core.security import redact, redact_payload
from app.db.tables.approvals import ApprovalRecord, DraftRecord
from app.db.tables.artifacts import ArtifactRecord
from app.db.tables.consultant_plus import ConsultantPlusSearchEventRecord
from app.db.tables.grants import CapabilityGrantRecord
from app.db.tables.reliability import (
    DeadLetterEntryRecord,
    ExecutionCheckpointRecord,
    ProviderCallRecord,
)
from app.db.tables.reviews import ResultReviewRecord
from app.db.tables.tasks import TaskRecord, TaskStepRecord
from app.integrations.consultant_plus.factory import ConsultantPlusProviderLike
from app.models.accounting import AccountingResult
from app.models.agent import AgentGrant, AgentResult, require_grant
from app.models.digest import DIGEST_VERSION, DailyOwnerDigest
from app.models.enums import (
    AgentType,
    PolicyDecision,
    RiskLevel,
    TaskCategory,
    TaskState,
)
from app.models.legal import LegalResult
from app.models.office import OfficeResult, SecurityResult
from app.models.process import ProcessGraph
from app.models.task import LegalClarification, TaskCreate, TaskResponse, TaskStepPlan
from app.office.executors import (
    NODE_EXECUTORS,
    OfficeRunContext,
)
from app.office.executors import (
    alias_outputs as _alias_outputs,
)
from app.office.executors import (
    result_for_action as _result_for_action,
)
from app.office.executors import (
    result_for_node_id as _result_for_node_id,
)
from app.orchestrator.budget import decimal_cost, record_model_usage, reserve_node
from app.orchestrator.capabilities import capability_for_node
from app.orchestrator.contracts import ProcessDefinitionV2, ProcessNodeSpec, RunBudget, RunUsage
from app.orchestrator.graph import GraphExecutor, NodeExecution
from app.orchestrator.passport import ProcessDefinitionV3
from app.orchestrator.processes import process_from_snapshot
from app.orchestrator.service import Orchestrator
from app.orchestrator.state_machine import validate_transition
from app.orchestrator.validation import validate_step_graph
from app.prompts.legal import LEGAL_PROMPT_VERSION
from app.repositories.tasks import TaskRepository
from app.services.approvals import audit, payload_hash, request_approval
from app.services.contour_state import get_runtime
from app.services.legal_analysis import extract_attachments
from app.services.process_graph import build_process_graph


class TaskService:
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

    async def _verify_attachments(
        self, attachment_ids: list[str], *, user_id: str, company_id: str
    ) -> None:
        for artifact_id in attachment_ids:
            artifact = await self.session.get(ArtifactRecord, artifact_id)
            if (
                artifact is None
                or artifact.owner_id != user_id
                or artifact.company_id != company_id
            ):
                raise ArtifactNotFoundError(artifact_id)

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

        await self._verify_attachments(payload.attachment_ids, user_id=user_id, company_id=company_id)
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

    async def create_rework(
        self,
        source: TaskRecord,
        *,
        target_node_ids: list[str],
        user_id: str,
        company_id: str,
    ) -> TaskResponse:
        """Create a new immutable run for selected graph work and its safety closure."""

        if source.process_snapshot is None or source.run_budget_snapshot is None:
            raise RuntimeError("Result has no executable process snapshot")
        process = process_from_snapshot(source.process_snapshot)
        if not isinstance(process, (ProcessDefinitionV2, ProcessDefinitionV3)):
            raise RuntimeError("Legacy process results cannot be reworked")
        budget = RunBudget.model_validate(source.run_budget_snapshot)
        next_cycle = source.rework_cycle + 1
        if next_cycle > budget.max_rework_cycles:
            raise RunBudgetExceededError("RUN_REWORK_LIMIT_REACHED")
        source_nodes = {
            step.node_id
            for step in await self.repository.list_steps(source.id)
            if step.node_id is not None
        }
        unknown = set(target_node_ids) - source_nodes
        if unknown:
            raise ValueError("Rework target is not a node of the reviewed task")
        if source.company_id != company_id:
            raise TaskNotFoundError(source.id)
        request = TaskCreate.model_validate(source.request_data)
        child = await self.repository.create(
            user_id=user_id,
            payload=request,
            company_id=company_id,
        )
        child.process_snapshot = source.process_snapshot
        child.run_budget_snapshot = source.run_budget_snapshot
        child.run_usage = RunUsage(rework_cycles=next_cycle).model_dump(mode="json")
        child.rework_parent_task_id = source.id
        child.rework_target_node_ids = target_node_ids
        child.rework_cycle = next_cycle
        audit(
            self.session,
            source,
            "rework_started",
            {"task_id": child.id, "target_node_ids": target_node_ids, "cycle": next_cycle},
        )
        return await self._execute(
            request,
            user_id=user_id,
            company_id=company_id,
            existing_task=child,
        )

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
        request = TaskCreate(
            message=task.input_text,
            attachment_ids=task.attachment_ids,
            requested_agent=requested_agent_from_record(task),
            jurisdiction=payload.jurisdiction,
            effective_on=payload.effective_on,
            invoice_id=task.request_data.get("invoice_id"),
            requested_action=task.request_data.get("requested_action", "analyze"),
        )
        task.request_data = request.model_dump(mode="json")
        if queued:
            from app.jobs import publish

            await self.session.commit()
            try:
                await asyncio.to_thread(publish, task.id)
            except Exception:
                await self._publish_failed(task)
            return self.to_response(task)
        return await self._execute(
            request,
            user_id=user_id,
            company_id=company_id,
            existing_task=task,
        )

    async def _execute(
        self,
        payload: TaskCreate,
        *,
        user_id: str,
        existing_task: TaskRecord | None = None,
        idempotency_key: str | None = None,
        company_id: str,
    ) -> TaskResponse:
        await self._verify_attachments(payload.attachment_ids, user_id=user_id, company_id=company_id)
        if existing_task is not None:
            task = existing_task
        else:
            task, created = await self.repository.create_once(
                user_id=user_id,
                payload=payload,
                key=idempotency_key,
                company_id=company_id,
            )
            if not created:
                return self.to_response(task)
        await self.session.commit()
        task_id = task.id
        try:
            await self._transition(task, TaskState.CLASSIFYING)
            routing, plan = await self.orchestrator.prepare(
                text=payload.message,
                requested_agent=payload.requested_agent,
            )
            await self.repository.set_routing(
                task,
                category=routing.category,
                risk_level=routing.risk_level,
            )
            is_legal = self.lawyer is not None and routing.category == TaskCategory.LEGAL
            requires_office = (
                payload.process_id == "daily_cash_and_receivable_risk"
                or routing.category in {TaskCategory.ACCOUNTING, TaskCategory.SECURITY, TaskCategory.MIXED}
                or payload.invoice_id is not None
            )
            if requires_office and self.lawyer is None:
                result = AgentResult(
                    agent=AgentType.ORCHESTRATOR,
                    status="unsupported",
                    summary="Office flows require a lawyer agent; none is configured.",
                    warnings=["LAWYER_UNAVAILABLE"],
                )
                await self.repository.set_result(task, result.model_dump(mode="json"))
                audit(self.session, task, "office_requires_lawyer", {"process_id": payload.process_id})
                await self._transition(task, TaskState.FAILED)
                await self.session.commit()
                return self.to_response(task)
            if self.lawyer is not None and requires_office:
                return await self._execute_office(task, payload, routing.required_agents, user_id)
            if is_legal and (payload.jurisdiction is None or payload.effective_on is None):
                assert self.lawyer is not None
                clarification = await self.lawyer.execute(
                    text=payload.message,
                    user_id=user_id,
                    company_id=company_id,
                    jurisdiction=payload.jurisdiction,
                    effective_on=payload.effective_on,
                    artifact_ids=payload.attachment_ids,
                )
                await self.repository.set_result(task, clarification.model_dump(mode="json"))
                await self._transition(task, TaskState.WAITING_INPUT)
                await self.session.commit()
                return self.to_response(task)
            if is_legal:
                plan[0].agent = AgentType.LAWYER
                plan[0].action = "legal_retrieval_pilot"
                plan[0].expected_output_schema = "LegalResult"
            await self._transition(task, TaskState.PLANNING)

            validate_step_graph(plan)
            step_records = [await self.repository.add_step(task, step) for step in plan]
            await self._transition(task, TaskState.RUNNING)
            step_records[0].state = TaskState.RUNNING.value
            step_records[0].started_at = datetime.now(UTC)
            await self.session.commit()

            result: AgentResult
            if is_legal:
                assert self.lawyer is not None
                runtime = await get_runtime(
                    self.session, company_id=company_id, process_id=payload.process_id
                )
                if not runtime.process_enabled:
                    result = AgentResult(
                        agent=AgentType.LAWYER,
                        status="stopped_by_switch",
                        summary=(
                            "Процесс остановлен kill switch. Выполняется ручной режим; "
                            "новые запуски запрещены до включения владельцем."
                        ),
                        warnings=["KILL_SWITCH_PROCESS"],
                    )
                    await self.repository.set_result(task, result.model_dump(mode="json"))
                    audit(self.session, task, "kill_switch_stop", {"process_id": payload.process_id})
                    await self._transition(task, TaskState.WAITING_INPUT)
                    await self.session.commit()
                    return self.to_response(task)
                started = perf_counter()
                result = await self.lawyer.execute(
                    text=payload.message,
                    user_id=user_id,
                    company_id=company_id,
                    jurisdiction=payload.jurisdiction,
                    effective_on=payload.effective_on,
                    artifact_ids=payload.attachment_ids,
                )
                latency_ms = round((perf_counter() - started) * 1000)
                self.session.add(
                    ProviderCallRecord(
                        company_id=company_id,
                        task_id=task.id,
                        step_id=step_records[0].id,
                        node_id="legal_query",
                        provider=AgentType.LAWYER.value,
                        operation="legal_retrieval_pilot",
                        machine_identity=machine_identity_for(AgentType.LAWYER),
                        status="succeeded",
                        attempt=1,
                        result_hash=payload_hash(result.model_dump(mode="json")),
                        latency_ms=latency_ms,
                        finished_at=datetime.now(UTC),
                    )
                )
                if isinstance(result, LegalResult):
                    self._audit_consultant_trail(task, result)
                if result.status == "waiting_source":
                    # The mandatory licensed source is unavailable: stop cleanly.
                    await self.repository.set_result(task, result.model_dump(mode="json"))
                    audit(self.session, task, "waiting_source", {"provider_status": "unavailable"})
                    await self._transition(task, TaskState.WAITING_SOURCE)
                    await self.session.commit()
                    return self.to_response(task)
            else:
                result, latency_ms = await self.orchestrator.execute(
                    task_id=task.id,
                    step=plan[0],
                    user_id=user_id,
                    text=payload.message,
                    artifact_ids=payload.attachment_ids,
                )
            step_records[0].state = TaskState.COMPLETED.value
            if isinstance(result, LegalResult) and result.findings:
                severity = {
                    RiskLevel.LOW: 0,
                    RiskLevel.MEDIUM: 1,
                    RiskLevel.HIGH: 2,
                    RiskLevel.CRITICAL: 3,
                }
                risk = max(
                    [routing.risk_level, *(finding.risk_level for finding in result.findings)],
                    key=severity.__getitem__,
                )
                await self.repository.set_routing(task, category=routing.category, risk_level=risk)
            step_records[0].completed_at = datetime.now(UTC)
            step_records[0].output = redact_payload(result.model_dump(mode="json"))
            await self.repository.save_agent_run(
                task_id=task.id,
                step_id=step_records[0].id,
                agent_type=result.agent.value,
                input_data={**payload.model_dump(mode="json"), "message": redact(payload.message)},
                output_data=result.model_dump(mode="json"),
                latency_ms=latency_ms,
                prompt_version=(
                    LEGAL_PROMPT_VERSION
                    if isinstance(result, LegalResult) and result.analysis_attempted
                    else "legal-retrieval-v1"
                    if is_legal
                    else "dummy-v1"
                ),
                model_id=result.analysis_model if isinstance(result, LegalResult) else "mock",
            )
            await self.repository.set_result(task, result.model_dump(mode="json"))
            audit(self.session, task, "task_result", {"status": result.status})
            await self._transition(task, TaskState.COMPLETED)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            refreshed = await self.repository.get(task_id)
            if refreshed and TaskState(refreshed.state) not in {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            }:
                await self.repository.update_state(refreshed, TaskState.FAILED)
                for step in await self.repository.list_steps(task_id):
                    if step.state == TaskState.RUNNING.value:
                        step.state = TaskState.FAILED.value
                        step.error_code = "AGENT_EXECUTION_FAILED"
                        step.completed_at = datetime.now(UTC)
                await self.session.commit()
            raise
        return self.to_response(task)

    async def _execute_office(
        self,
        task: TaskRecord,
        payload: TaskCreate,
        agents: list[AgentType],
        user_id: str,
    ) -> TaskResponse:
        """Execute the persisted office DAG instead of a hand-written agent loop."""

        assert self.lawyer is not None
        if self.accounting_provider is None:
            raise RuntimeError(
                "TaskService requires an injected accounting provider for office flows"
            )
        accounting_provider = self.accounting_provider
        lawyer_agent = self.lawyer
        if task.process_snapshot is None or task.run_budget_snapshot is None:
            raise RuntimeError("Office task is missing its executable process snapshot")
        process = process_from_snapshot(task.process_snapshot)
        if not isinstance(process, (ProcessDefinitionV2, ProcessDefinitionV3)):
            raise RuntimeError("Queued task uses a legacy process that cannot be graph-executed")
        # REL-006: the owner's kill switch stops the whole process immediately.
        runtime = await get_runtime(self.session, company_id=task.company_id, process_id=process.id)
        if not runtime.process_enabled:
            result = AgentResult(
                agent=AgentType.ORCHESTRATOR,
                status="stopped_by_switch",
                summary=(
                    "Процесс остановлен kill switch. Выполняется ручной режим; "
                    "новые запуски запрещены до включения владельцем."
                ),
                warnings=["KILL_SWITCH_PROCESS"],
            )
            await self.repository.set_result(task, result.model_dump(mode="json"))
            audit(self.session, task, "kill_switch_stop", {"process_id": process.id})
            await self._transition(task, TaskState.WAITING_INPUT)
            await self.session.commit()
            return self.to_response(task)
        if not runtime.llm_enabled and lawyer_agent is not None:
            # The external LLM switch feeds the lawyer an explicit "no provider".
            lawyer_agent = LawyerAgent(lawyer_agent.knowledge, None, consultant=self.consultant)
        write_tools_enabled = runtime.write_tools_enabled
        # TZ 7.1: only A2+ may produce drafts; A0/A1 are read/recommend only.
        autonomy_allows_write = runtime.autonomy_level in {"a2_draft", "a3_approved_action"}
        budget = RunBudget.model_validate(task.run_budget_snapshot)
        selected = list(dict.fromkeys(agents))
        if payload.invoice_id and AgentType.ACCOUNTANT not in selected:
            selected.insert(0, AgentType.ACCOUNTANT)
        selected = [
            agent for agent in selected if agent not in {AgentType.SECURITY, AgentType.ORCHESTRATOR}
        ]
        if AgentType.LAWYER in selected and (
            payload.jurisdiction is None or payload.effective_on is None
        ):
            result = await self.lawyer.execute(
                text=payload.message,
                user_id=user_id,
                company_id=task.company_id,
                jurisdiction=payload.jurisdiction,
                effective_on=payload.effective_on,
                artifact_ids=payload.attachment_ids,
            )
            await self.repository.set_result(task, result.model_dump(mode="json"))
            await self._transition(task, TaskState.WAITING_INPUT)
            await self.session.commit()
            return self.to_response(task)

        specs = {spec.id: spec for spec in process.nodes}
        selected_nodes = (
            [
                "accounting_snapshot",
                "cash_control",
                "receivable_risk",
                "security_preflight",
                "security_postflight",
            ]
            if process.id == "daily_cash_and_receivable_risk"
            else [
                *(["accounting_snapshot"] if AgentType.ACCOUNTANT in selected else []),
                "security_preflight",
                *(["legal_review"] if AgentType.LAWYER in selected else []),
                "security_postflight",
            ]
        )
        if task.rework_target_node_ids:
            selected_nodes = _rework_execution_scope(
                process,
                selected_nodes,
                task.rework_target_node_ids,
            )
        if any(node_id not in specs for node_id in selected_nodes):
            raise RuntimeError("Process snapshot cannot execute the requested office route")
        # Resume from the last confirmed checkpoint: completed nodes keep their
        # persisted outputs and step ids; only pending nodes re-execute (REL-008).
        completed_outputs = await self._completed_node_outputs(task, specs)
        completed_step_ids = await self._completed_step_ids(task)
        step_ids = {
            **completed_step_ids,
            **{
                node_id: new_id("step")
                for node_id in selected_nodes
                if node_id not in completed_step_ids
            },
        }
        pending_nodes = [node_id for node_id in selected_nodes if node_id not in completed_outputs]
        pending_set = set(pending_nodes)
        plans: list[TaskStepPlan] = []
        for node_id in pending_nodes:
            spec = specs[node_id]
            # Dependencies on already-completed nodes are satisfied by the
            # resumed checkpoint outputs, not by plans of this run.
            dependencies = [
                step_ids[dependency] for dependency in spec.depends_on if dependency in pending_set
            ]
            if node_id == "security_postflight":
                dependencies = [step_ids[prior] for prior in pending_nodes if prior != node_id]
            plans.append(
                TaskStepPlan(
                    step_id=step_ids[node_id],
                    node_id=spec.id,
                    agent=spec.agent,
                    action=spec.action,
                    depends_on=dependencies,
                    input_refs=list(spec.input_refs),
                    timeout_seconds=60,
                    max_attempts=spec.retry_policy.max_attempts,
                    retryable_error_codes=list(spec.retry_policy.retryable_error_codes),
                    backoff_seconds=0.5,
                    risk_level=spec.risk_level,
                    expected_output_schema=spec.expected_output_schema,
                    estimated_llm_calls=spec.estimated_llm_calls,
                    estimated_cost_rub=spec.estimated_cost_rub,
                )
            )
        validate_step_graph(plans)
        await self._transition(task, TaskState.PLANNING)
        steps = [await self.repository.add_step(task, plan) for plan in plans]
        step_by_id = {step.id: step for step in steps}
        await self._transition(task, TaskState.RUNNING)
        await self.session.commit()

        documents = await extract_attachments(
            self.lawyer.knowledge,
            payload.attachment_ids,
            user_id,
            task.company_id,
        )
        security_agent = SecurityAgent()

        issued_grants: dict[str, tuple[AgentGrant, ...]] = {}

        async def claim_batch(batch: tuple[TaskStepPlan, ...]) -> None:
            await self._check_running(task)
            usage = RunUsage.model_validate(task.run_usage or {})
            moment = datetime.now(UTC)
            for plan in batch:
                usage = reserve_node(budget, usage, plan, now=moment)
            for plan in batch:
                if not await self.repository.claim_step(task, step_by_id[plan.step_id]):
                    raise RuntimeError("Graph node is no longer available for execution")
                # Machine identity + short-lived least-privilege grants are
                # issued per step, persisted, and re-checked before the call.
                principal = principal_for(plan.agent)
                issued_grants[plan.step_id] = tuple(
                    AgentGrant(data_scope=scope, actions=actions, expires_at=expires_at)
                    for scope, actions, expires_at in issue_capability_grants(
                        plan.node_id or "", issued_at=moment
                    )
                )
                for grant in issued_grants[plan.step_id]:
                    self.session.add(
                        CapabilityGrantRecord(
                            company_id=task.company_id,
                            task_id=task.id,
                            step_id=plan.step_id,
                            node_id=plan.node_id or "",
                            principal_id=principal.principal_id,
                            data_scope=grant.data_scope.value,
                            actions=",".join(grant.actions),
                            policy_version=POLICY_VERSION,
                            issued_at=moment,
                            expires_at=grant.expires_at,
                        )
                    )
            task.run_usage = usage.model_dump(mode="json")
            await self.session.commit()

        step_to_node = {sid: node for node, sid in step_ids.items()}

        run_context = OfficeRunContext(
            accounting_provider=accounting_provider,
            lawyer_agent=lawyer_agent,
            consultant=self.consultant,
            security_agent=security_agent,
            documents=documents,
            message=payload.message,
            invoice_id=payload.invoice_id,
            jurisdiction=payload.jurisdiction,
            effective_on=payload.effective_on,
            attachment_ids=payload.attachment_ids,
            requested_action=payload.requested_action,
            user_id=user_id,
            company_id=task.company_id,
            as_of=payload.effective_on or datetime.now(UTC).date(),
        )

        async def run_node(
            plan: TaskStepPlan, completed: Mapping[str, AgentResult]
        ) -> NodeExecution:
            completed = _alias_outputs(completed, step_to_node, specs)
            started = perf_counter()
            # Enforcement happens immediately before the provider call, not
            # only at issuance: no valid grant, no data access.
            capability = capability_for_node(plan.node_id)
            if capability is not None:
                now = datetime.now(UTC)
                for scope in capability.data_scopes:
                    require_grant(issued_grants.get(plan.step_id, ()), scope, now=now)
            executor = NODE_EXECUTORS.get(plan.action)
            if executor is None:
                raise RuntimeError(f"No executor registered for process action {plan.action}")
            component = await executor(run_context, plan, completed, plans)
            return NodeExecution(
                output=component,
                latency_ms=round((perf_counter() - started) * 1000),
            )

        async def complete_node(plan: TaskStepPlan, execution: NodeExecution) -> None:
            await self._check_running(task)
            step = step_by_id[plan.step_id]
            component = execution.output
            step.state = TaskState.COMPLETED.value
            step.completed_at = datetime.now(UTC)
            step.output = redact_payload(component.model_dump(mode="json"))
            now = datetime.now(UTC)
            output_json = component.model_dump(mode="json")
            self.session.add(
                ExecutionCheckpointRecord(
                    company_id=task.company_id,
                    task_id=task.id,
                    step_id=step.id,
                    node_id=plan.node_id,
                    checkpoint_hash=payload_hash(output_json),
                    kind="node_completed",
                )
            )
            self.session.add(
                ProviderCallRecord(
                    company_id=task.company_id,
                    task_id=task.id,
                    step_id=step.id,
                    node_id=plan.node_id,
                    provider=plan.agent.value,
                    operation=plan.action,
                    machine_identity=machine_identity_for(plan.agent),
                    status="succeeded",
                    attempt=execution.attempts,
                    result_hash=payload_hash(output_json),
                    latency_ms=execution.latency_ms,
                    finished_at=now,
                )
            )
            await self.repository.save_agent_run(
                task_id=task.id,
                step_id=step.id,
                agent_type=plan.agent.value,
                input_data={"task_id": task.id, "invoice_id": payload.invoice_id},
                output_data=step.output,
                latency_ms=execution.latency_ms,
                prompt_version=LEGAL_PROMPT_VERSION
                if isinstance(component, LegalResult)
                else "deterministic-v1",
                model_id=component.analysis_model
                if isinstance(component, LegalResult)
                else "none-deterministic",
            )
            model_calls = component.model_calls if isinstance(component, LegalResult) else []
            usage = record_model_usage(
                budget,
                RunUsage.model_validate(task.run_usage or {}),
                input_tokens=sum(call.input_tokens or 0 for call in model_calls),
                output_tokens=sum(call.output_tokens or 0 for call in model_calls),
                observed_cost_rub=sum(
                    (decimal_cost(call.cost) for call in model_calls), Decimal("0")
                ),
            )
            task.run_usage = usage.model_dump(mode="json")
            await self.session.commit()

        resume_mapping = {
            step_ids[node_id]: output for node_id, output in completed_outputs.items()
        }
        try:
            outputs = await GraphExecutor(plans).execute(
                claim_batch=claim_batch,
                run_node=run_node,
                complete_node=complete_node,
                resume=resume_mapping,
            )
        except RunBudgetExceededError as error:
            return await self._pause_for_budget(task, error)
        except NodeExecutionFailed as failure:
            return await self._fail_safe(task, failure, step_by_id)

        outputs_view = _alias_outputs(outputs, step_to_node, specs)
        preflight = _result_for_action(plans, outputs_view, "security_preflight")
        accounting = _result_for_node_id(plans, outputs_view, "accounting_snapshot")
        legal = _result_for_action(plans, outputs_view, "lawyer_pilot")
        security = _result_for_action(plans, outputs_view, "security_postflight")
        if not isinstance(preflight, SecurityResult) or not isinstance(security, SecurityResult):
            raise RuntimeError("Office graph finished without required security controls")
        accounting_result = accounting if isinstance(accounting, AccountingResult) else None
        legal_result = legal if isinstance(legal, LegalResult) else None
        if legal_result is not None:
            self._audit_consultant_trail(task, legal_result)
            if legal_result.status == "waiting_source":
                return await self._pause_for_waiting_source(task, legal_result)
        if process.id == "daily_cash_and_receivable_risk":
            # The accepted result of the daily pilot is the owner digest (TZ 6.2):
            # an aggregation of ALL node outputs, not just the accounting snapshot.
            outputs_view = _alias_outputs(outputs, step_to_node, specs)
            digest = await asyncio.to_thread(
                build_daily_digest,
                self.accounting_provider,
                as_of=payload.effective_on or datetime.now(UTC).date(),
                snapshot=(
                    snapshot
                    if isinstance(
                        snapshot := _result_for_node_id(plans, outputs_view, "accounting_snapshot"),
                        AccountingResult,
                    )
                    else None
                ),
                cash=(
                    cash_out
                    if isinstance(
                        cash_out := _result_for_node_id(plans, outputs_view, "cash_control"),
                        AccountingResult,
                    )
                    else None
                ),
                receivables=(
                    receivable_report
                    if isinstance(
                        receivable_report := _result_for_node_id(
                            plans, outputs_view, "receivable_risk"
                        ),
                        AccountingResult,
                    )
                    else None
                ),
            )
            await self.repository.set_result(task, digest.model_dump(mode="json"))
            audit(
                self.session,
                task,
                "daily_digest",
                {
                    "watermark": digest.watermark,
                    "cash_available": digest.cash_available,
                    "receivable_total": digest.receivable_total,
                    "risks": len(digest.top_nonpayment_risks),
                },
            )
            await self._transition(task, TaskState.COMPLETED)
            await self.session.commit()
            return self.to_response(task)
        office = await self._finalize_office_result(
            task,
            action=payload.requested_action,
            accounting=accounting_result,
            legal=legal_result,
            security=security,
            write_tools_enabled=write_tools_enabled,
            autonomy_allows_write=autonomy_allows_write,
        )
        await self.repository.set_result(task, office.model_dump(mode="json"))
        await self._transition(
            task, TaskState.WAITING_APPROVAL if office.requires_approval else TaskState.COMPLETED
        )
        await self.session.commit()
        return self.to_response(task)

    async def _finalize_office_result(
        self,
        task: TaskRecord,
        *,
        action: str,
        accounting: AccountingResult | None,
        legal: LegalResult | None,
        security: SecurityResult,
        write_tools_enabled: bool = True,
        autonomy_allows_write: bool = True,
    ) -> OfficeResult:
        """Apply the deterministic policy matrix and finish the task accordingly."""
        decision, reasons = decide(
            action=action,
            accounting=accounting,
            legal=legal,
            security=security,
            write_tools_enabled=write_tools_enabled,
            autonomy_allows_write=autonomy_allows_write,
        )
        office = OfficeResult(
            agent=AgentType.ORCHESTRATOR,
            status="office_report",
            summary="Сводный результат проверок. Реальные действия не выполнялись.",
            accounting=accounting,
            legal=legal,
            security=security,
            policy_decision=decision,
            policy_version=POLICY_VERSION,
            policy_reasons=reasons,
            requires_approval=decision == PolicyDecision.REQUIRE_OWNER_APPROVAL,
            findings=[
                *(accounting.findings if accounting else []),
                *(legal.findings if legal else []),
                *security.findings,
            ],
            warnings=["SYNTHETIC_PILOT: требуется проверка специалистами."],
        )
        if office.requires_approval:
            approval = await request_approval(self.session, task, office)
            office.approval_id = approval.id
            office.status = "waiting_approval"
        elif decision == PolicyDecision.ALLOW_DRAFT:
            # Within the limit: a non-posted synthetic draft is allowed without a
            # separate owner approval. It never posts a document or pays.
            draft = DraftRecord(
                company_id=task.company_id,
                approval_id=None,
                owner_id=task.user_id,
                payload={"action": "create_mock_payment_draft", "auto": True},
            )
            self.session.add(draft)
            await self.session.flush()
            office.draft_id = draft.id
            office.status = "draft_created_synthetically"
        elif decision == PolicyDecision.ESCALATE:
            office.status = "escalated_to_human"
        elif decision == PolicyDecision.OWNER_ONLY_OUTSIDE_AGENT:
            office.status = "owner_manual_action_required"
        elif decision == PolicyDecision.DENY:
            office.status = "action_denied"
        if office.findings:
            levels = list(RiskLevel)
            task.risk_level = max((f.risk_level for f in office.findings), key=levels.index).value
        audit(self.session, task, "office_result", {"policy": decision.value, "reasons": reasons})
        return office

    async def _pause_for_waiting_source(self, task: TaskRecord, legal: LegalResult) -> TaskResponse:
        """The mandatory external legal source is unavailable: stop, never guess."""
        self._audit_consultant_trail(task, legal)
        await self.repository.set_result(task, legal.model_dump(mode="json"))
        audit(self.session, task, "waiting_source", {"provider_status": "unavailable"})
        await self._transition(task, TaskState.WAITING_SOURCE)
        await self.session.commit()
        return self.to_response(task)

    def _audit_consultant_trail(self, task: TaskRecord, legal: LegalResult) -> None:
        """Journal Consultant+ search metadata; the licensed text is never copied."""
        trail = legal.consultant_plus
        if trail is None:
            return
        if not trail.searched:
            self.session.add(
                ConsultantPlusSearchEventRecord(
                    company_id=task.company_id,
                    task_id=task.id,
                    owner_id=task.user_id,
                    outcome="unavailable",
                    details={"mode": trail.mode, "provider_status": trail.provider_status},
                )
            )
            return
        outcome = "found" if trail.queries else "not_found"
        for item in trail.queries:
            self.session.add(
                ConsultantPlusSearchEventRecord(
                    company_id=task.company_id,
                    task_id=task.id,
                    owner_id=task.user_id,
                    outcome=outcome,
                    query_id=item.query_id,
                    source_id=item.source_id,
                    jurisdiction=item.jurisdiction,
                    edition=item.edition,
                    locator=item.locator,
                    effective_from=item.effective_from,
                    effective_to=item.effective_to,
                    searched_at=item.retrieved_at,
                    details={"document_type": item.document_type, "authority": item.authority},
                )
            )

    async def _load_completed_steps(self, task: TaskRecord) -> list[TaskStepRecord]:
        rows = await self.session.execute(
            select(TaskStepRecord).where(
                TaskStepRecord.task_id == task.id,
                TaskStepRecord.state == TaskState.COMPLETED.value,
                TaskStepRecord.node_id.is_not(None),
                TaskStepRecord.output.is_not(None),
            )
        )
        return list(rows.scalars())

    async def _completed_step_ids(self, task: TaskRecord) -> dict[str, str]:
        """Map node_id -> persisted step id for confirmed (completed) nodes."""
        return {
            step.node_id: step.id
            for step in await self._load_completed_steps(task)
            if step.node_id is not None
        }

    async def _completed_node_outputs(
        self, task: TaskRecord, specs: dict[str, ProcessNodeSpec]
    ) -> dict[str, AgentResult]:
        """Load confirmed node outputs to resume a run from its checkpoint."""
        outputs: dict[str, AgentResult] = {}
        for step in await self._load_completed_steps(task):
            spec = specs.get(step.node_id or "")
            if spec is None:
                continue
            payload = step.output
            if not isinstance(payload, dict):
                continue
            try:
                outputs[spec.id] = GraphExecutor.load_output(spec.expected_output_schema, payload)
            except ModelOutputInvalidError:
                continue
        return outputs

    async def _fail_safe(
        self, task: TaskRecord, failure: NodeExecutionFailed, step_by_id: dict[str, TaskStepRecord]
    ) -> TaskResponse:
        """A node exhausted its retries: controlled stop, DLQ entry, human review."""
        step = step_by_id.get(failure.step_id)
        if step is not None:
            step.state = TaskState.FAILED.value
            step.error_code = failure.error_code
            step.completed_at = datetime.now(UTC)
        # Siblings claimed in the same layer never finished: release them back
        # to queued so a checkpoint resume can re-claim them.
        for sibling in await self.repository.list_steps(task.id):
            if sibling.id != failure.step_id and sibling.state == TaskState.RUNNING.value:
                sibling.state = TaskState.QUEUED.value
        self.session.add(
            ProviderCallRecord(
                company_id=task.company_id,
                task_id=task.id,
                step_id=failure.step_id,
                node_id=failure.node_id,
                provider="node_execution",
                operation="graph_node",
                machine_identity=machine_identity_for(AgentType.ORCHESTRATOR),
                status="failed",
                attempt=failure.attempts,
                error_code=failure.error_code,
                finished_at=datetime.now(UTC),
            )
        )
        self.session.add(
            DeadLetterEntryRecord(
                company_id=task.company_id,
                task_id=task.id,
                step_id=failure.step_id,
                node_id=failure.node_id,
                error_code=failure.error_code,
                error_class="NodeExecutionFailed",
                attempts=failure.attempts,
                owner_id=task.user_id,
            )
        )
        result = AgentResult(
            agent=AgentType.ORCHESTRATOR,
            status="failed_safe",
            summary=(
                "Выполнение остановлено после исчерпания повторов узла. "
                "Внешних действий не выполнено; возможен повтор с контрольной точки."
            ),
            warnings=[failure.error_code],
        )
        await self.repository.set_result(task, result.model_dump(mode="json"))
        audit(
            self.session,
            task,
            "node_failed_safe",
            {
                "node_id": failure.node_id,
                "error_code": failure.error_code,
                "attempts": failure.attempts,
            },
        )
        await self._transition(task, TaskState.FAILED_SAFE)
        await self.session.commit()
        return self.to_response(task)

    async def _pause_for_budget(
        self, task: TaskRecord, error: RunBudgetExceededError
    ) -> TaskResponse:
        """Budget exhaustion is a human decision point, never an implicit failure."""

        result = AgentResult(
            agent=AgentType.ORCHESTRATOR,
            status="waiting_human",
            summary="Выполнение остановлено лимитом процесса; требуется решение владельца.",
            warnings=[error.code],
        )
        await self.repository.set_result(task, result.model_dump(mode="json"))
        audit(self.session, task, "run_budget_paused", {"reason": error.code})
        await self._transition(task, TaskState.WAITING_INPUT)
        await self.session.commit()
        return self.to_response(task)

    async def _check_running(self, task: TaskRecord) -> None:
        state = await self.session.scalar(
            select(TaskRecord.state).where(TaskRecord.id == task.id).with_for_update()
        )
        if state != "running":
            raise InvalidStateTransitionError(str(state), "running")

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


def requested_agent_from_record(task: TaskRecord) -> AgentType | None:
    return AgentType(task.requested_agent) if task.requested_agent else None


def _rework_execution_scope(
    process: ProcessDefinitionV2 | ProcessDefinitionV3,
    active_nodes: list[str],
    targets: list[str],
) -> list[str]:
    """Select requested nodes, their downstream, and required safety inputs.

    Reusing a predecessor output would make a rework depend on stale evidence.
    The closure therefore reruns only the minimal upstream control nodes needed
    to execute the selected downstream branch safely.
    """

    active = set(active_nodes)
    if not set(targets) <= active:
        raise ValueError("Rework target is not active for this task route")
    specs = {node.id: node for node in process.nodes}
    dependents = {
        node.id: {candidate.id for candidate in process.nodes if node.id in candidate.depends_on}
        for node in process.nodes
    }
    selected = set(targets)
    frontier = list(targets)
    while frontier:
        node_id = frontier.pop()
        for dependent in dependents[node_id] & active:
            if dependent not in selected:
                selected.add(dependent)
                frontier.append(dependent)
    frontier = list(selected)
    while frontier:
        node_id = frontier.pop()
        for dependency in specs[node_id].depends_on:
            if dependency in active and dependency not in selected:
                selected.add(dependency)
                frontier.append(dependency)
    return [node_id for node_id in active_nodes if node_id in selected]
