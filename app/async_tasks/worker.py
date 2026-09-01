from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.approvals import ApprovalService
from app.async_tasks.models import (
    AsyncExecutionCheckpoint,
    AsyncRunStatus,
    AsyncTaskCreate,
    NotificationStatus,
)
from app.async_tasks.policy import (
    STEP_LEVEL_EXECUTION_CONSTRAINTS,
    AsyncTaskPolicyGate,
)
from app.async_tasks.repository import AsyncTaskRepository
from app.audit import AuditWriter
from app.db.models import ApprovalRow
from app.openclaw import (
    CriterionVerification,
    GovernanceResult,
    OpenClawExecutionRequest,
    OpenClawExecutionResult,
    OpenClawTransportError,
)
from app.planning.failure import ExecutionFailureClass
from app.planning.models import (
    ExecutionEvidence,
    Plan,
    PlanNode,
    PlanNodeExecution,
    PlanNodeKind,
    PlanNodeState,
)
from app.planning.outcome import OutcomeDisposition, OutcomeJudge, OutcomeJudgement
from app.planning.replanner import PlanReplanner, ReplanDisposition
from app.planning.repository import PlanPersistenceConflict, PlanRepository
from app.planning.scheduler import PlanNodeScheduler
from app.planning.truth import PlanningTruthError, PlanningTruthInspector
from app.projects.repository import ProjectRepository
from app.safety_intent import (
    analyze_safety_intent,
    is_read_only_core_status_intent,
    requests_database_quick_check,
)
from app.tasks import TaskRepository, TaskService, TaskStatus

RETRY_DELAYS_SECONDS = (5, 30)


class AsyncTaskExecutor(Protocol):
    async def execute(
        self,
        request: OpenClawExecutionRequest,
    ) -> OpenClawExecutionResult: ...


CoreStatusProbe = Callable[[], Awaitable[dict[str, Any]]]


class AsyncTaskWorker:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        audit_writer: AuditWriter,
        policy_gate: AsyncTaskPolicyGate,
        executor: AsyncTaskExecutor,
        worker_id: str,
        lease_seconds: int,
        clock: Callable[[], datetime] | None = None,
        core_status_probe: CoreStatusProbe | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.audit_writer = audit_writer
        self.policy_gate = policy_gate
        self.executor = executor
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.core_status_probe = core_status_probe or self._probe_local_core_status

    async def run_once(self) -> bool:
        now = self._now()
        with self.session_factory() as session:
            repository = AsyncTaskRepository(
                session,
                audit_writer=self.audit_writer,
            )
            run = repository.claim_next(
                worker_id=self.worker_id,
                now=now,
                lease_seconds=self.lease_seconds,
            )
            if run is None:
                session.rollback()
                return False

            task_service = self._task_service(session)
            task = task_service.get(run.task_id)
            request = AsyncTaskCreate.model_validate_json(run.request_json)
            decision = self.policy_gate.evaluate(request)

            if not decision.allowed:
                repository.transition(
                    run.id,
                    AsyncRunStatus.BLOCKED,
                    now=now,
                    error_code=decision.reason_code,
                    error_message=decision.message,
                )
                task_service.transition(
                    task.id,
                    TaskStatus.BLOCKED,
                    result_summary=decision.message,
                )
                self._mark_terminal_notification(
                    repository,
                    run.id,
                    run.source_chat_id,
                    now,
                )
                session.commit()
                return True

            if self._reconcile_plan_before_execution(
                session=session,
                repository=repository,
                task_service=task_service,
                run=run,
                request=request,
                now=now,
            ):
                session.commit()
                return True

            checkpoint = AsyncExecutionCheckpoint(
                stage="running",
                message="Core execution started.",
                uncertain_side_effect=False,
                updated_at=now,
            )
            repository.transition(
                run.id,
                AsyncRunStatus.RUNNING,
                now=now,
                checkpoint_json=checkpoint.model_dump_json(),
            )
            if task.status in {
                TaskStatus.QUEUED,
                TaskStatus.VERIFYING,
            }:
                task_service.transition(
                    task.id,
                    TaskStatus.RUNNING,
                )
            session.commit()

        with self.session_factory() as plan_session:
            persisted_plan = PlanRepository(plan_session).get(run.id)
        if persisted_plan is not None:
            await self._execute_planned_run(
                run.id,
                run.task_id,
                request,
            )
            return True

        if self._is_core_health_ready_workflow(request):
            self._block_planned_run(
                run.id,
                run.task_id,
                error_code="plan_missing",
                reason=(
                    "Core-native health/ready execution requires a durable plan "
                    "and Outcome Judge contract."
                ),
            )
            return True

        execution_request = OpenClawExecutionRequest(
            task_id=run.task_id,
            run_id=run.id,
            attempt=run.attempt,
            idempotency_key=f"{run.id}:{run.attempt}",
            project_id=request.project_id,
            goal=request.goal,
            mode=request.mode.value,
            workspace=request.workspace,
            constraints=self._execution_constraints(request),
        )

        try:
            result = await self.executor.execute(execution_request)
        except OpenClawTransportError as error:
            self._handle_transport_error(
                run.id,
                run.task_id,
                error,
            )
            return True

        self._persist_result(
            run.id,
            run.task_id,
            result,
        )
        return True

    def _reconcile_plan_before_execution(
        self,
        *,
        session: Session,
        repository: AsyncTaskRepository,
        task_service: TaskService,
        run: Any,
        request: AsyncTaskCreate,
        now: datetime,
    ) -> bool:
        plan_repository = PlanRepository(session)
        try:
            plan = plan_repository.get(run.id)
        except ValidationError:
            reason = "Persisted plan payload is invalid."
            repository.transition(
                run.id,
                AsyncRunStatus.BLOCKED,
                now=now,
                error_code="replan_plan_invalid",
                error_message=reason,
            )
            task_service.transition(
                run.task_id,
                TaskStatus.BLOCKED,
                result_summary=reason,
            )
            self._mark_terminal_notification(repository, run.id, run.source_chat_id, now)
            return True
        if plan is None:
            return False

        try:
            fresh_truth = PlanningTruthInspector(ProjectRepository(session)).inspect(
                request.project_id, request.workspace
            )
        except PlanningTruthError as error:
            reason = str(error)
            repository.transition(
                run.id,
                AsyncRunStatus.BLOCKED,
                now=now,
                error_code="replan_truth_unavailable",
                error_message=reason,
            )
            task_service.transition(
                run.task_id,
                TaskStatus.BLOCKED,
                result_summary=reason,
            )
            self._mark_terminal_notification(repository, run.id, run.source_chat_id, now)
            return True

        execution_started = (
            run.attempt > 1 or run.checkpoint_json is not None or run.external_run_id is not None
        )
        try:
            decision = PlanReplanner().reconcile(
                plan,
                fresh_truth,
                execution_started=execution_started,
            )
            if decision.disposition is ReplanDisposition.REVISED:
                plan_repository.save(
                    workflow_id=run.id,
                    task_id=run.task_id,
                    plan=decision.plan,
                )
                return False
        except (ValidationError, PlanPersistenceConflict):
            reason = "Plan reconciliation payload is invalid or conflicting."
            repository.transition(
                run.id,
                AsyncRunStatus.BLOCKED,
                now=now,
                error_code="replan_plan_invalid",
                error_message=reason,
            )
            current_task = task_service.get(run.task_id)
            if current_task.status is not TaskStatus.BLOCKED:
                task_service.transition(
                    run.task_id,
                    TaskStatus.BLOCKED,
                    result_summary=reason,
                )
            self._mark_terminal_notification(repository, run.id, run.source_chat_id, now)
            return True
        if decision.disposition is ReplanDisposition.BLOCKED:
            repository.transition(
                run.id,
                AsyncRunStatus.BLOCKED,
                now=now,
                error_code="replan_blocked",
                error_message=decision.reason,
            )
            current_task = task_service.get(run.task_id)
            if current_task.status is not TaskStatus.BLOCKED:
                task_service.transition(
                    run.task_id,
                    TaskStatus.BLOCKED,
                    result_summary=decision.reason,
                )
            self._mark_terminal_notification(repository, run.id, run.source_chat_id, now)
            return True
        return False

    async def _execute_planned_run(
        self,
        run_id: str,
        task_id: str,
        request: AsyncTaskCreate,
    ) -> None:
        scheduler = PlanNodeScheduler()
        for _ in range(256):
            with self.session_factory() as session:
                plan = PlanRepository(session).get(run_id)
            if plan is None:
                self._block_planned_run(
                    run_id,
                    task_id,
                    error_code="plan_missing",
                    reason="Durable plan disappeared during execution.",
                )
                return
            ready = scheduler.ready_nodes(plan)
            if not ready:
                running = next(
                    (item for item in plan.node_executions if item.state is PlanNodeState.RUNNING),
                    None,
                )
                if running is not None:
                    self._mark_planned_uncertain_side_effect(run_id, task_id, running.node_id)
                    return
                if self._resume_planned_terminal_state(run_id, task_id, plan):
                    return
                self._block_planned_run(
                    run_id,
                    task_id,
                    error_code="plan_stalled",
                    reason="Plan has no ready node and is not complete.",
                )
                return
            node = ready[0]
            if node.kind is PlanNodeKind.APPROVAL_GATE:
                disposition = self._evaluate_planned_approval_gate(
                    run_id, task_id, request, plan, node
                )
                if disposition == "continue":
                    continue
                return
            if node.kind is PlanNodeKind.VERIFICATION_GATE:
                disposition = self._evaluate_planned_verification(
                    run_id,
                    task_id,
                    plan,
                    node,
                )
                if disposition == "continue":
                    continue
                return
            if node.kind is not PlanNodeKind.ACTION:
                self._block_planned_run(
                    run_id,
                    task_id,
                    error_code="plan_node_unsupported",
                    reason=f"Unsupported ready node kind: {node.kind.value}.",
                )
                return
            prepared = self._prepare_planned_action(
                run_id,
                task_id,
                request,
                plan,
                node,
            )
            if prepared is None:
                return
            execution_request = prepared
            provenance = "openclaw"
            try:
                if self._is_core_health_ready_workflow(request):
                    provenance = "core"
                    result = await self._execute_core_health_ready_workflow(
                        dod_criteria=plan.definition_of_done.criteria,
                        require_database_quick_check=requests_database_quick_check(
                            analyze_safety_intent(request.goal)
                        ),
                    )
                else:
                    result = await self.executor.execute(execution_request)
                    if (
                        result.provider == "local"
                        and result.profile is not None
                        and result.profile.startswith("visualforge-")
                    ):
                        provenance = "visualforge"
            except OpenClawTransportError as error:
                if self._planned_retry_budget_exhausted(run_id, error):
                    self._mark_planned_budget_exhausted(
                        run_id,
                        task_id,
                        node.id,
                        "Automatic retry budget is exhausted.",
                    )
                    self._block_planned_run(
                        run_id,
                        task_id,
                        error_code="budget_exhausted",
                        reason="Automatic retry budget is exhausted.",
                    )
                    return
                self._record_planned_transport_failure(
                    run_id,
                    task_id,
                    node.id,
                    error,
                )
                self._handle_transport_error(run_id, task_id, error)
                return
            terminal = self._record_planned_action_result(
                run_id,
                task_id,
                node.id,
                result,
                provenance=provenance,
            )
            if terminal:
                self._persist_result(run_id, task_id, result)
                return
        self._block_planned_run(
            run_id,
            task_id,
            error_code="plan_loop_exhausted",
            reason="Plan execution loop exceeded its deterministic safety bound.",
        )

    def _prepare_planned_action(
        self,
        run_id: str,
        task_id: str,
        request: AsyncTaskCreate,
        plan: Plan,
        node: PlanNode,
    ) -> OpenClawExecutionRequest | None:
        budget = plan.execution_budget
        started_at = budget.started_at
        if started_at is not None:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            elapsed = (self._now() - started_at).total_seconds()
            if elapsed >= budget.max_elapsed_seconds:
                judgement = OutcomeJudgement(
                    disposition=OutcomeDisposition.BLOCKED,
                    reason_code="budget_exhausted",
                    reason="Wall-clock execution budget is exhausted.",
                )
                blocked_plan = plan.model_copy(
                    update={"outcome_judgement": judgement.model_dump(mode="json")}
                )
                with self.session_factory() as session:
                    PlanRepository(session).save(
                        workflow_id=run_id,
                        task_id=task_id,
                        plan=blocked_plan,
                    )
                    session.commit()
                self._block_planned_run(
                    run_id,
                    task_id,
                    error_code="budget_exhausted",
                    reason=judgement.reason,
                )
                return None
        if budget.actions_used >= budget.max_actions:
            judgement = OutcomeJudgement(
                disposition=OutcomeDisposition.BLOCKED,
                reason_code="budget_exhausted",
                reason="Action execution budget is exhausted.",
            )
            blocked_plan = plan.model_copy(
                update={"outcome_judgement": judgement.model_dump(mode="json")}
            )
            with self.session_factory() as session:
                PlanRepository(session).save(
                    workflow_id=run_id,
                    task_id=task_id,
                    plan=blocked_plan,
                )
                session.commit()
            self._block_planned_run(
                run_id,
                task_id,
                error_code="budget_exhausted",
                reason=judgement.reason,
            )
            return None
        current = self._node_execution(plan, node.id)
        attempts = current.attempts + 1
        running = current.model_copy(update={"state": PlanNodeState.RUNNING, "attempts": attempts})
        started_at = budget.started_at or self._now()
        updated_budget = budget.model_copy(
            update={
                "actions_used": budget.actions_used + 1,
                "started_at": started_at,
            }
        )
        running_plan = plan.model_copy(
            update={
                "node_executions": self._replace_execution(plan, running),
                "execution_budget": updated_budget,
            }
        )
        with self.session_factory() as session:
            run = AsyncTaskRepository(session).get(run_id)
            PlanRepository(session).save(
                workflow_id=run_id,
                task_id=task_id,
                plan=running_plan,
            )
            session.commit()
        constraints = tuple(
            dict.fromkeys(
                self._execution_constraints(request)
                + tuple(item.description for item in running_plan.constraints)
            )
        )
        remaining_actions = max(
            updated_budget.max_actions - updated_budget.actions_used,
            0,
        )
        return OpenClawExecutionRequest(
            task_id=task_id,
            run_id=run_id,
            attempt=run.attempt,
            idempotency_key=(
                f"{run_id}:{run.attempt}:r{running_plan.revision}:{node.id}:a{attempts}"
            ),
            project_id=request.project_id,
            goal=request.goal,
            mode=request.mode.value,
            workspace=request.workspace,
            constraints=constraints,
            plan_node_id=node.id,
            plan_node_title=node.title,
            capability_requirements=tuple(item.value for item in node.capability_requirements),
            dod_criteria=running_plan.definition_of_done.criteria,
            verification_requirements=tuple(
                item.description for item in running_plan.verification_requirements
            ),
            prior_evidence=tuple(f"{item.id}: {item.summary}" for item in running_plan.evidence),
            remaining_budget={
                "actions": remaining_actions,
                "replans": max(
                    running_plan.risk_budget.max_replans - (running_plan.revision - 1),
                    0,
                ),
            },
        )

    def _record_planned_action_result(
        self,
        run_id: str,
        task_id: str,
        node_id: str,
        result: OpenClawExecutionResult,
        *,
        provenance: str = "openclaw",
    ) -> bool:
        with self.session_factory() as session:
            plan = PlanRepository(session).get(run_id)
            assert plan is not None
            current = self._node_execution(plan, node_id)
            evidence = ExecutionEvidence(
                id=(f"ev:{node_id}:r{plan.revision}:a{current.attempts}"),
                node_id=node_id,
                kind="result",
                summary=result.summary,
                artifact_refs=tuple(str(item) for item in result.files_changed),
                verification_refs=tuple(
                    ref for item in result.criterion_verification for ref in item.evidence_refs
                ),
                external_run_id=result.external_run_id,
                outcome=result.outcome,
                criterion_verification=tuple(
                    item.model_dump(mode="json") for item in result.criterion_verification
                ),
                result_payload=result.model_dump(mode="json"),
                provenance=provenance,
                created_at=self._now(),
            )
            target_state = {
                "completed": PlanNodeState.COMPLETED,
                "blocked": PlanNodeState.BLOCKED,
                "failed": PlanNodeState.FAILED,
            }[result.outcome]
            updated_execution = current.model_copy(
                update={
                    "state": target_state,
                    "evidence_ids": current.evidence_ids + (evidence.id,),
                    "last_failure_class": (
                        None if result.outcome == "completed" else result.error_code
                    ),
                }
            )
            evidence_items = plan.evidence
            if all(item.id != evidence.id for item in evidence_items):
                evidence_items = evidence_items + (evidence,)
            updated_plan = plan.model_copy(
                update={
                    "node_executions": self._replace_execution(
                        plan,
                        updated_execution,
                    ),
                    "evidence": evidence_items,
                }
            )
            PlanRepository(session).save(
                workflow_id=run_id,
                task_id=task_id,
                plan=updated_plan,
            )
            session.commit()
        return result.outcome != "completed"

    def _plan_with_explicit_unmet_final_action_failure(
        self,
        plan: Plan,
        judgement: OutcomeJudgement,
    ) -> Plan:
        if (
            judgement.disposition is not OutcomeDisposition.REPLAN
            or judgement.reason_code != "dod_unmet"
        ):
            return plan
        node_id = self._last_action_node_id(plan)
        execution = self._node_execution(plan, node_id)
        if execution.state is not PlanNodeState.COMPLETED:
            return plan

        unmet_criteria = {
            " ".join(item.criterion.split())
            for item in judgement.criteria
            if not item.satisfied and item.status == "unmet"
        }
        if not execution.evidence_ids:
            return plan
        latest_evidence_id = execution.evidence_ids[-1]
        latest_evidence = next(
            (item for item in plan.evidence if item.id == latest_evidence_id),
            None,
        )
        if latest_evidence is None or latest_evidence.kind != "result":
            return plan
        if not any(
            raw.get("status") == "unmet"
            and " ".join(str(raw.get("criterion", "")).split()) in unmet_criteria
            for raw in latest_evidence.criterion_verification
        ):
            return plan

        failed_execution = execution.model_copy(
            update={
                "state": PlanNodeState.FAILED,
                "last_failure_class": ExecutionFailureClass.DOD_UNMET_RECOVERABLE.value,
            }
        )
        return plan.model_copy(
            update={
                "node_executions": self._replace_execution(plan, failed_execution),
                "outcome_judgement": judgement.model_dump(mode="json"),
            }
        )

    def _evaluate_planned_verification(
        self,
        run_id: str,
        task_id: str,
        plan: Plan,
        node: PlanNode,
    ) -> str:
        result = self._result_from_plan_evidence(plan)
        judgement = OutcomeJudge().judge(plan, result)
        if judgement.disposition is OutcomeDisposition.SATISFIED:
            verify_execution = self._node_execution(plan, node.id).model_copy(
                update={"state": PlanNodeState.COMPLETED}
            )
            satisfied_plan = plan.model_copy(
                update={
                    "node_executions": self._replace_execution(
                        plan,
                        verify_execution,
                    ),
                    "outcome_judgement": judgement.model_dump(mode="json"),
                }
            )
            with self.session_factory() as session:
                PlanRepository(session).save(
                    workflow_id=run_id,
                    task_id=task_id,
                    plan=satisfied_plan,
                )
                session.commit()
            self._persist_result(run_id, task_id, result)
            return "terminal"
        if judgement.disposition is OutcomeDisposition.REPLAN:
            replan_plan = self._plan_with_explicit_unmet_final_action_failure(
                plan,
                judgement,
            )
            return self._replan_after_judgement(
                run_id,
                task_id,
                replan_plan,
                judgement,
            )
        terminal_result = OpenClawExecutionResult(
            outcome=(
                "blocked" if judgement.disposition is OutcomeDisposition.BLOCKED else "failed"
            ),
            summary=judgement.reason,
            error_code=judgement.reason_code,
        )
        terminal_plan = plan.model_copy(
            update={"outcome_judgement": judgement.model_dump(mode="json")}
        )
        with self.session_factory() as session:
            PlanRepository(session).save(
                workflow_id=run_id,
                task_id=task_id,
                plan=terminal_plan,
            )
            session.commit()
        self._persist_result(run_id, task_id, terminal_result)
        return "terminal"

    def _evaluate_planned_approval_gate(
        self,
        run_id: str,
        task_id: str,
        request: AsyncTaskCreate,
        plan: Plan,
        node: PlanNode,
    ) -> str:
        with self.session_factory() as session:
            approval = (
                session.query(ApprovalRow)
                .filter_by(workflow_id=run_id, task_id=task_id)
                .order_by(ApprovalRow.requested_at.desc())
                .first()
            )
        if approval is None or approval.action_hash != ApprovalService.action_hash(request.goal):
            self._block_planned_run(
                run_id,
                task_id,
                error_code="approval_required",
                reason="Matching owner approval is required before this plan action.",
            )
            return "terminal"
        if approval.status == "approved":
            execution = self._node_execution(plan, node.id).model_copy(
                update={"state": PlanNodeState.COMPLETED}
            )
            updated = plan.model_copy(
                update={"node_executions": self._replace_execution(plan, execution)}
            )
            with self.session_factory() as session:
                PlanRepository(session).save(workflow_id=run_id, task_id=task_id, plan=updated)
                session.commit()
            return "continue"
        if approval.status == "denied":
            code = "approval_denied"
            reason = "Owner approval was denied."
        else:
            code = "approval_required"
            reason = "Owner approval is required before this plan action."
        self._block_planned_run(run_id, task_id, error_code=code, reason=reason)
        return "terminal"

    def _replan_after_judgement(
        self,
        run_id: str,
        task_id: str,
        plan: Plan,
        judgement: OutcomeJudgement,
    ) -> str:
        started_at = plan.execution_budget.started_at
        if started_at is not None:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            elapsed = (self._now() - started_at).total_seconds()
            if elapsed >= plan.execution_budget.max_elapsed_seconds:
                self._mark_planned_budget_exhausted(
                    run_id,
                    task_id,
                    self._last_action_node_id(plan),
                    "Wall-clock execution budget is exhausted before replan.",
                )
                self._block_planned_run(
                    run_id,
                    task_id,
                    error_code="budget_exhausted",
                    reason="Wall-clock execution budget is exhausted before replan.",
                )
                return "terminal"
        if plan.execution_budget.actions_used >= plan.execution_budget.max_actions:
            reason = "Action execution budget is exhausted before replan."
            self._mark_planned_budget_exhausted(
                run_id, task_id, self._last_action_node_id(plan), reason
            )
            self._block_planned_run(run_id, task_id, error_code="budget_exhausted", reason=reason)
            return "terminal"
        if plan.revision - 1 >= plan.risk_budget.max_replans:
            reason = "Automatic replan budget is exhausted."
            self._mark_planned_budget_exhausted(
                run_id, task_id, self._last_action_node_id(plan), reason
            )
            self._block_planned_run(run_id, task_id, error_code="budget_exhausted", reason=reason)
            return "terminal"
        failure_class = (
            ExecutionFailureClass.DOD_UNMET_RECOVERABLE
            if judgement.reason_code == "dod_unmet"
            else ExecutionFailureClass.DOD_EVIDENCE_MISSING
        )
        action_nodes = [item for item in plan.nodes if item.kind is PlanNodeKind.ACTION]
        if not action_nodes:
            self._block_planned_run(
                run_id,
                task_id,
                error_code=judgement.reason_code,
                reason=judgement.reason,
            )
            return "terminal"
        replan_action = next(
            (
                item
                for item in reversed(action_nodes)
                if self._node_execution(plan, item.id).state
                in {PlanNodeState.PENDING, PlanNodeState.FAILED}
            ),
            None,
        )
        if replan_action is None:
            blocked_plan = plan.model_copy(
                update={"outcome_judgement": judgement.model_dump(mode="json")}
            )
            with self.session_factory() as session:
                PlanRepository(session).save(workflow_id=run_id, task_id=task_id, plan=blocked_plan)
                session.commit()
            self._block_planned_run(
                run_id,
                task_id,
                error_code=judgement.reason_code,
                reason=judgement.reason,
            )
            return "terminal"
        failure = ExecutionEvidence(
            id=f"ev:{replan_action.id}:r{plan.revision}:dod",
            node_id=replan_action.id,
            kind="dod",
            summary=judgement.reason,
            outcome="failed",
            provenance="core_outcome_judge",
            created_at=self._now(),
        )
        failed_execution = self._node_execution(
            plan,
            replan_action.id,
        ).model_copy(
            update={
                "state": PlanNodeState.FAILED,
                "last_failure_class": failure_class.value,
                "evidence_ids": self._node_execution(
                    plan,
                    replan_action.id,
                ).evidence_ids
                + (failure.id,),
            }
        )
        failed_plan = plan.model_copy(
            update={
                "node_executions": self._replace_execution(
                    plan,
                    failed_execution,
                ),
                "evidence": plan.evidence + (failure,),
                "outcome_judgement": judgement.model_dump(mode="json"),
            }
        )
        decision = PlanReplanner().reconcile_after_evidence(
            failed_plan,
            failure_class=failure_class,
            evidence=failure,
            execution_started=True,
        )
        if decision.disposition is ReplanDisposition.REVISED:
            with self.session_factory() as session:
                PlanRepository(session).save(
                    workflow_id=run_id,
                    task_id=task_id,
                    plan=decision.plan,
                )
                session.commit()
            return "continue"
        blocked_plan = failed_plan.model_copy(
            update={"outcome_judgement": judgement.model_dump(mode="json")}
        )
        with self.session_factory() as session:
            PlanRepository(session).save(
                workflow_id=run_id,
                task_id=task_id,
                plan=blocked_plan,
            )
            session.commit()
        self._block_planned_run(
            run_id,
            task_id,
            error_code=judgement.reason_code,
            reason=judgement.reason,
        )
        return "terminal"

    @staticmethod
    def _result_from_plan_evidence(plan: Plan) -> OpenClawExecutionResult:
        criterion_items: list[CriterionVerification] = []
        latest_payload: dict[str, object] | None = None
        for evidence in plan.evidence:
            if evidence.result_payload is not None:
                latest_payload = evidence.result_payload
            for raw in evidence.criterion_verification:
                criterion_items.append(CriterionVerification.model_validate(raw))
        if latest_payload is not None:
            latest = OpenClawExecutionResult.model_validate(latest_payload)
            return latest.model_copy(update={"criterion_verification": tuple(criterion_items)})
        summary = (
            plan.evidence[-1].summary
            if plan.evidence
            else "No durable execution evidence is available."
        )
        return OpenClawExecutionResult(
            outcome="completed",
            summary=summary,
            artifacts={"evidence_ids": [item.id for item in plan.evidence]},
            verification={
                "method": "core_outcome_judge",
                "evidence_count": len(plan.evidence),
            },
            criterion_verification=tuple(criterion_items),
        )

    def _planned_retry_budget_exhausted(
        self,
        run_id: str,
        error: OpenClawTransportError,
    ) -> bool:
        if not error.retryable or error.uncertain_side_effect:
            return False
        with self.session_factory() as session:
            plan = PlanRepository(session).get(run_id)
            run = AsyncTaskRepository(session).get(run_id)
        if plan is None:
            return False
        return (
            run.attempt < run.max_attempts
            and plan.execution_budget.retries_used >= plan.risk_budget.max_retries
        )

    def _mark_planned_budget_exhausted(
        self,
        run_id: str,
        task_id: str,
        node_id: str,
        reason: str,
    ) -> None:
        with self.session_factory() as session:
            plan = PlanRepository(session).get(run_id)
            if plan is None:
                return
            current = self._node_execution(plan, node_id).model_copy(
                update={
                    "state": PlanNodeState.FAILED,
                    "last_failure_class": "budget_exhausted",
                }
            )
            judgement = OutcomeJudgement(
                disposition=OutcomeDisposition.BLOCKED,
                reason_code="budget_exhausted",
                reason=reason,
            )
            updated = plan.model_copy(
                update={
                    "node_executions": self._replace_execution(plan, current),
                    "outcome_judgement": judgement.model_dump(mode="json"),
                }
            )
            PlanRepository(session).save(
                workflow_id=run_id,
                task_id=task_id,
                plan=updated,
            )
            session.commit()

    def _record_planned_transport_failure(
        self,
        run_id: str,
        task_id: str,
        node_id: str,
        error: OpenClawTransportError,
    ) -> None:
        with self.session_factory() as session:
            plan = PlanRepository(session).get(run_id)
            if plan is None:
                return
            current = self._node_execution(plan, node_id)
            state = (
                PlanNodeState.PENDING
                if error.retryable and not error.uncertain_side_effect
                else (
                    PlanNodeState.BLOCKED if error.uncertain_side_effect else PlanNodeState.FAILED
                )
            )
            updated = current.model_copy(
                update={
                    "state": state,
                    "last_failure_class": error.code,
                }
            )
            budget = plan.execution_budget
            updated_budget = budget.model_copy(
                update={
                    "retries_used": budget.retries_used
                    + (1 if state is PlanNodeState.PENDING else 0)
                }
            )
            updated_plan = plan.model_copy(
                update={
                    "node_executions": self._replace_execution(plan, updated),
                    "execution_budget": updated_budget,
                }
            )
            PlanRepository(session).save(
                workflow_id=run_id,
                task_id=task_id,
                plan=updated_plan,
            )
            session.commit()

    def _mark_planned_uncertain_side_effect(self, run_id: str, task_id: str, node_id: str) -> None:
        reason = "A previously running plan node has no durable result; side effect is uncertain."
        with self.session_factory() as session:
            plan = PlanRepository(session).get(run_id)
            assert plan is not None
            execution = self._node_execution(plan, node_id).model_copy(
                update={
                    "state": PlanNodeState.BLOCKED,
                    "last_failure_class": "uncertain_side_effect",
                }
            )
            judgement = OutcomeJudgement(
                disposition=OutcomeDisposition.BLOCKED,
                reason_code="uncertain_side_effect",
                reason=reason,
            )
            updated = plan.model_copy(
                update={
                    "node_executions": self._replace_execution(plan, execution),
                    "outcome_judgement": judgement.model_dump(mode="json"),
                }
            )
            PlanRepository(session).save(workflow_id=run_id, task_id=task_id, plan=updated)
            session.commit()
        self._block_planned_run(run_id, task_id, error_code="uncertain_side_effect", reason=reason)

    def _resume_planned_terminal_state(
        self,
        run_id: str,
        task_id: str,
        plan: Plan,
    ) -> bool:
        judgement = plan.outcome_judgement or {}
        all_completed = all(
            self._node_execution(plan, node.id).state is PlanNodeState.COMPLETED
            for node in plan.nodes
        )
        if all_completed and judgement.get("disposition") == "satisfied":
            self._persist_result(run_id, task_id, self._result_from_plan_evidence(plan))
            return True
        terminal = next(
            (
                item
                for item in plan.node_executions
                if item.state in {PlanNodeState.BLOCKED, PlanNodeState.FAILED}
            ),
            None,
        )
        if terminal is None:
            return False
        evidence_by_id = {item.id: item for item in plan.evidence}
        for evidence_id in reversed(terminal.evidence_ids):
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or evidence.result_payload is None:
                continue
            try:
                result = OpenClawExecutionResult.model_validate(evidence.result_payload)
            except ValidationError:
                continue
            if result.outcome != "completed":
                self._persist_result(run_id, task_id, result)
                return True
        if terminal.state is PlanNodeState.BLOCKED:
            self._block_planned_run(
                run_id,
                task_id,
                error_code="uncertain_side_effect",
                reason=(
                    "A durable blocked plan node has no terminal result; "
                    "side effect status is uncertain."
                ),
            )
            return True
        self._persist_result(
            run_id,
            task_id,
            OpenClawExecutionResult(
                outcome="failed",
                summary="A durably failed plan node resumed at its terminal state.",
                error_code=terminal.last_failure_class or "execution_failed",
            ),
        )
        return True

    def _block_planned_run(
        self,
        run_id: str,
        task_id: str,
        *,
        error_code: str,
        reason: str,
    ) -> None:
        result = OpenClawExecutionResult(
            outcome="blocked",
            summary=reason,
            error_code=error_code,
        )
        self._persist_result(run_id, task_id, result)

    @staticmethod
    def _last_action_node_id(plan: Plan) -> str:
        for node in reversed(plan.nodes):
            if node.kind is PlanNodeKind.ACTION:
                return node.id
        return plan.nodes[-1].id

    @staticmethod
    def _node_execution(plan: Plan, node_id: str) -> PlanNodeExecution:
        for execution in plan.node_executions:
            if execution.node_id == node_id:
                return execution
        return PlanNodeExecution(node_id=node_id)

    @staticmethod
    def _replace_execution(
        plan: Plan,
        replacement: PlanNodeExecution,
    ) -> tuple[PlanNodeExecution, ...]:
        updated: list[PlanNodeExecution] = []
        replaced = False
        for execution in plan.node_executions:
            if execution.node_id == replacement.node_id:
                updated.append(replacement)
                replaced = True
            else:
                updated.append(execution)
        if not replaced:
            updated.append(replacement)
        return tuple(updated)

    @staticmethod
    def _execution_constraints(
        request: AsyncTaskCreate,
    ) -> tuple[str, ...]:
        if request.approval_required or request.risk_level >= 2:
            return tuple(dict.fromkeys(request.constraints + STEP_LEVEL_EXECUTION_CONSTRAINTS))
        return request.constraints

    @staticmethod
    def _is_core_health_ready_workflow(
        request: AsyncTaskCreate,
    ) -> bool:
        return is_read_only_core_status_intent(analyze_safety_intent(request.goal))

    async def _execute_core_health_ready_workflow(
        self,
        *,
        dod_criteria: tuple[str, ...] = (),
        require_database_quick_check: bool = False,
    ) -> OpenClawExecutionResult:
        statuses = await self.core_status_probe()
        health = statuses.get("health", {})
        ready = statuses.get("ready", {})
        health_ok = (
            isinstance(health, dict)
            and health.get("http_status") == 200
            and health.get("status") == "ok"
        )
        ready_ok = (
            isinstance(ready, dict)
            and ready.get("http_status") == 200
            and ready.get("status") == "ready"
        )
        database = statuses.get("database", {})
        if require_database_quick_check and not (
            isinstance(database, dict) and "quick_check" in database
        ):
            try:
                quick_check = await asyncio.to_thread(self._probe_database_quick_check)
            except Exception:
                quick_check = "unavailable"
            database = {"quick_check": quick_check}
        database_ok = isinstance(database, dict) and database.get("quick_check") == "ok"
        required_checks_ok = (
            health_ok and ready_ok and (database_ok if require_database_quick_check else True)
        )
        failed_checks: list[str] = []
        if not health_ok:
            failed_checks.append("/health")
        if not ready_ok:
            failed_checks.append("/ready")
        if require_database_quick_check and not database_ok:
            failed_checks.append("database quick_check")
        failure_explanation = (
            "Read-only verification failed: " + ", ".join(failed_checks) + " did not pass."
        )
        outcome: Literal["completed", "blocked"] = "completed" if required_checks_ok else "blocked"
        service = statuses.get("service", {})
        service_status = (
            service.get("status")
            if isinstance(service, dict) and service.get("status")
            else ("running" if health_ok else "unavailable")
        )
        quick_check_summary = (
            f", quick_check={database.get('quick_check')!s}"
            if require_database_quick_check and isinstance(database, dict)
            else ""
        )
        summary = (
            "Đã kiểm tra read-only: "
            f"Core service={service_status!s}, "
            f"/health={health.get('status')!s}, "
            f"/ready={ready.get('status')!s}{quick_check_summary}."
            if outcome == "completed"
            else (
                "Kiểm tra read-only chưa đạt: "
                f"Core service={service_status!s}, "
                f"/health={health.get('status')!s}, "
                f"/ready={ready.get('status')!s}{quick_check_summary}."
            )
        )
        return OpenClawExecutionResult(
            outcome=outcome,
            summary=summary,
            artifacts={
                "service": service,
                "health": health,
                "ready": ready,
                "database": database,
                "changes_made": "none",
                "file_changes": "none",
                "config_changes": "none",
                "service_restarts": "none",
            },
            verification={
                "method": "core_internal_http_get",
                "constraints_respected": [
                    "no_file_changes",
                    "no_config_changes",
                    "no_service_restart",
                    "no_model_provider_change",
                ],
            },
            files_changed=(),
            commands_run=(),
            tests=(),
            error_code=(
                "database_quick_check_failed"
                if require_database_quick_check and not database_ok
                else None
            ),
            profile="CE-2",
            criterion_verification=(
                tuple(
                    CriterionVerification(
                        criterion=criterion,
                        status="verified",
                        evidence_refs=(
                            "core:http:/health",
                            "core:http:/ready",
                            *(("core:db:quick_check",) if require_database_quick_check else ()),
                        ),
                        explanation=(
                            "Core-owned read-only health/ready probes passed"
                            + (
                                " and database quick_check returned ok."
                                if require_database_quick_check
                                else "."
                            )
                        ),
                    )
                    for criterion in dod_criteria
                )
                if outcome == "completed"
                else tuple(
                    CriterionVerification(
                        criterion=criterion,
                        status="unmet",
                        explanation=failure_explanation,
                    )
                    for criterion in dod_criteria
                )
            ),
        )

    async def _probe_local_core_status(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health = await self._probe_http_endpoint(
                client,
                "http://127.0.0.1:8790/health",
            )
            ready = await self._probe_http_endpoint(
                client,
                "http://127.0.0.1:8790/ready",
            )
        if "http_status" in health:
            service = {"status": "running", "evidence": "local_http:/health"}
        elif "http_status" in ready:
            service = {"status": "running", "evidence": "local_http:/ready"}
        else:
            service = {"status": "unavailable", "evidence": "local_http:no_response"}
        return {
            "service": service,
            "health": health,
            "ready": ready,
        }

    async def _probe_http_endpoint(
        self,
        client: Any,
        url: str,
    ) -> dict[str, Any]:
        try:
            response = await client.get(url)
        except httpx.HTTPError:
            return {"status": "unavailable"}
        return self._http_status_artifact(response)

    @staticmethod
    def _http_status_artifact(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        artifact = dict(payload) if isinstance(payload, dict) else {}
        artifact["http_status"] = response.status_code
        artifact.setdefault("status", "unknown")
        return artifact

    def _probe_database_quick_check(self) -> str | None:
        with self.session_factory() as session:
            return session.connection().exec_driver_sql("PRAGMA quick_check").scalar()

    def _handle_transport_error(
        self,
        run_id: str,
        task_id: str,
        error: OpenClawTransportError,
    ) -> None:
        now = self._now()
        safe_error_message = (
            "OpenClaw returned an invalid execution result contract."
            if error.code == "invalid_response_contract"
            else str(error)
        )
        with self.session_factory() as session:
            repository = AsyncTaskRepository(
                session,
                audit_writer=self.audit_writer,
            )
            run = repository.get(run_id)
            if run.status is AsyncRunStatus.CANCELLED:
                return

            task_service = self._task_service(session)
            if (
                error.retryable
                and not error.uncertain_side_effect
                and run.attempt < run.max_attempts
            ):
                delay = RETRY_DELAYS_SECONDS[
                    min(
                        run.attempt - 1,
                        len(RETRY_DELAYS_SECONDS) - 1,
                    )
                ]
                repository.schedule_retry(
                    run_id,
                    now=now,
                    delay_seconds=delay,
                    error_code=error.code,
                    error_message=safe_error_message,
                )
                session.commit()
                return

            target_run = (
                AsyncRunStatus.BLOCKED if error.uncertain_side_effect else AsyncRunStatus.FAILED
            )
            target_task = TaskStatus.BLOCKED if error.uncertain_side_effect else TaskStatus.FAILED
            terminal_checkpoint = AsyncExecutionCheckpoint(
                stage="terminal",
                message=safe_error_message,
                uncertain_side_effect=error.uncertain_side_effect,
                updated_at=now,
            )
            terminal = repository.transition(
                run_id,
                target_run,
                now=now,
                checkpoint_json=terminal_checkpoint.model_dump_json(),
                error_code=error.code,
                error_message=safe_error_message,
            )
            task_service.transition(
                task_id,
                target_task,
                result_summary=safe_error_message,
            )
            self._mark_terminal_notification(
                repository,
                run_id,
                terminal.source_chat_id,
                now,
            )
            session.commit()

    def _persist_result(
        self,
        run_id: str,
        task_id: str,
        result: OpenClawExecutionResult,
    ) -> None:
        now = self._now()
        result_json = result.model_dump_json()
        with self.session_factory() as session:
            repository = AsyncTaskRepository(
                session,
                audit_writer=self.audit_writer,
            )
            current = repository.get(run_id)
            if current.status is AsyncRunStatus.CANCELLED:
                return
            request = AsyncTaskCreate.model_validate_json(current.request_json)
            governed = request.governed_coding is not None

            task_service = self._task_service(session)
            repository.transition(
                run_id,
                AsyncRunStatus.VERIFYING,
                now=now,
                result_json=result_json,
                external_run_id=result.external_run_id,
            )
            task_service.transition(
                task_id,
                TaskStatus.VERIFYING,
            )

            if (
                governed
                and result.outcome == "completed"
                and not self._completed_governance_valid(result)
            ):
                result = result.model_copy(
                    update={
                        "outcome": "failed",
                        "summary": "Governance result missing or not verified; run failed closed.",
                        "error_code": "governance_result_invalid",
                    }
                )
                result_json = result.model_dump_json()
                run_status = AsyncRunStatus.FAILED
                task_status = TaskStatus.FAILED
            elif result.outcome == "completed":
                run_status = AsyncRunStatus.COMPLETED
                task_status = TaskStatus.COMPLETED
            elif result.outcome == "blocked":
                run_status = AsyncRunStatus.BLOCKED
                task_status = TaskStatus.BLOCKED
            else:
                run_status = AsyncRunStatus.FAILED
                task_status = TaskStatus.FAILED

            terminal = repository.transition(
                run_id,
                run_status,
                now=now,
                result_json=result_json,
                error_code=result.error_code,
                error_message=(result.summary if result.outcome != "completed" else None),
                external_run_id=result.external_run_id,
            )
            task_service.transition(
                task_id,
                task_status,
                result_summary=result.summary,
            )
            self._mark_terminal_notification(
                repository,
                run_id,
                terminal.source_chat_id,
                now,
            )
            session.commit()

    @staticmethod
    def _completed_governance_valid(result: OpenClawExecutionResult) -> bool:
        governance = result.governance_result
        return isinstance(governance, GovernanceResult) and (
            governance.decision == "allow" and governance.status in {"verified", "approved"}
        )

    @staticmethod
    def _mark_terminal_notification(
        repository: AsyncTaskRepository,
        run_id: str,
        source_chat_id: str | None,
        now: datetime,
    ) -> None:
        repository.mark_notification(
            run_id,
            status=(
                NotificationStatus.PENDING if source_chat_id else NotificationStatus.NOT_REQUIRED
            ),
            now=now,
        )

    def _task_service(
        self,
        session: Session,
    ) -> TaskService:
        return TaskService(
            TaskRepository(session),
            self.audit_writer,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
