from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.async_tasks import AsyncRunStatus, AsyncTaskRepository, AsyncTaskWorker
from app.db.models import WorkflowRow
from app.openclaw import (
    CriterionVerification,
    OpenClawExecutionResult,
    OpenClawTransportError,
)
from app.planning.models import (
    DefinitionOfDone,
    ExecutionBudget,
    ExecutionEvidence,
    PlanNode,
    PlanNodeExecution,
    PlanNodeKind,
    PlanNodeState,
    RiskBudget,
)
from app.planning.repository import PlanRepository
from app.tasks import TaskRepository, TaskService, TaskStatus
from tests.integration.test_async_task_worker import (
    NOW,
    SequenceExecutor,
    _audit,
    _seed_run,
    _worker,
)
from tests.integration.test_async_task_worker import (
    engine as engine,
)
from tests.integration.test_async_task_worker import (
    session_factory as session_factory,
)


def _replace_plan(
    factory: sessionmaker[Session],
    run_id: str,
    task_id: str,
    *,
    max_replans: int = 1,
    max_retries: int = 2,
    budget: ExecutionBudget | None = None,
    executions: tuple[PlanNodeExecution, ...] = (),
    evidence: tuple[ExecutionEvidence, ...] = (),
) -> None:
    with factory() as session:
        repository = PlanRepository(session)
        original = repository.get(run_id)
        assert original is not None
        plan = original.model_copy(
            update={
                "definition_of_done": DefinitionOfDone(
                    criteria=("source collected", "analysis verified")
                ),
                "risk_budget": RiskBudget(
                    max_replans=max_replans,
                    max_retries=max_retries,
                ),
                "nodes": (
                    PlanNode(
                        id="collect",
                        title="Collect source",
                        kind=PlanNodeKind.ACTION,
                    ),
                    PlanNode(
                        id="analyze",
                        title="Analyze source",
                        kind=PlanNodeKind.ACTION,
                        depends_on=("collect",),
                    ),
                    PlanNode(
                        id="verify",
                        title="Verify DoD",
                        kind=PlanNodeKind.VERIFICATION_GATE,
                        depends_on=("analyze",),
                    ),
                ),
                "node_executions": executions,
                "evidence": evidence,
                "execution_budget": budget or ExecutionBudget(max_actions=4),
            }
        )
        repository.save(workflow_id=run_id, task_id=task_id, plan=plan)
        session.commit()


async def _run_and_load(
    factory: sessionmaker[Session],
    tmp_path,
    executor: SequenceExecutor,
    run_id: str,
    task_id: str,
):
    worker = _worker(
        session_factory=factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )
    processed = await worker.run_once()
    with factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(TaskRepository(session), _audit(tmp_path)).get(task_id)
        plan = PlanRepository(session).get(run_id)
    assert plan is not None
    return processed, run, task, plan


@pytest.mark.asyncio
async def test_two_action_plan_completes_only_after_outcome_judge(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="plan-two-action",
    )
    _replace_plan(session_factory, run_id, task_id)
    executor = SequenceExecutor(
        [
            OpenClawExecutionResult(
                outcome="completed",
                summary="source collected",
                criterion_verification=(
                    CriterionVerification(
                        criterion="source collected",
                        status="verified",
                        evidence_refs=("ev_source",),
                    ),
                ),
            ),
            OpenClawExecutionResult(
                outcome="completed",
                summary="analysis complete",
                criterion_verification=(
                    CriterionVerification(
                        criterion="source collected",
                        status="verified",
                        evidence_refs=("ev_source",),
                    ),
                    CriterionVerification(
                        criterion="analysis verified",
                        status="verified",
                        evidence_refs=("ev_analysis",),
                    ),
                ),
            ),
        ]
    )

    processed, run, task, plan = await _run_and_load(
        session_factory, tmp_path, executor, run_id, task_id
    )

    assert processed is True
    assert run.status is AsyncRunStatus.COMPLETED
    assert task.status is TaskStatus.COMPLETED
    assert [request.plan_node_id for request in executor.requests] == [
        "collect",
        "analyze",
    ]
    states = {item.node_id: item.state for item in plan.node_executions}
    assert states == {
        "collect": PlanNodeState.COMPLETED,
        "analyze": PlanNodeState.COMPLETED,
        "verify": PlanNodeState.COMPLETED,
    }
    assert plan.execution_budget.actions_used == 2
    assert len(plan.evidence) == 2
    assert plan.outcome_judgement is not None
    assert plan.outcome_judgement["disposition"] == "satisfied"


@pytest.mark.asyncio
async def test_resume_skips_completed_node_and_preserves_evidence(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="plan-resume",
    )
    prior = ExecutionEvidence(
        id="ev_prior",
        node_id="collect",
        kind="result",
        summary="source collected previously",
    )
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        executions=(
            PlanNodeExecution(
                node_id="collect",
                state=PlanNodeState.COMPLETED,
                attempts=1,
                evidence_ids=(prior.id,),
            ),
        ),
        evidence=(prior,),
        budget=ExecutionBudget(max_actions=4, actions_used=1, started_at=NOW),
    )
    executor = SequenceExecutor(
        [
            OpenClawExecutionResult(
                outcome="completed",
                summary="analysis complete",
                criterion_verification=(
                    CriterionVerification(
                        criterion="source collected",
                        status="verified",
                        evidence_refs=(prior.id,),
                    ),
                    CriterionVerification(
                        criterion="analysis verified",
                        status="verified",
                        evidence_refs=("ev_analysis",),
                    ),
                ),
            )
        ]
    )

    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert run.status is AsyncRunStatus.COMPLETED
    assert task.status is TaskStatus.COMPLETED
    assert [request.plan_node_id for request in executor.requests] == ["analyze"]
    assert plan.execution_budget.actions_used == 2
    assert plan.evidence[0].id == prior.id
    assert plan.node_executions[0].state is PlanNodeState.COMPLETED


@pytest.mark.asyncio
async def test_action_budget_exhaustion_blocks_without_executor_call(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="plan-budget",
    )
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        budget=ExecutionBudget(max_actions=1, actions_used=1, started_at=NOW),
    )
    executor = SequenceExecutor([])
    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "budget_exhausted"
    assert task.status is TaskStatus.BLOCKED
    assert plan.outcome_judgement is not None
    assert plan.outcome_judgement["reason_code"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_missing_dod_evidence_fails_closed_when_replan_budget_is_zero(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="plan-no-evidence",
    )
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        max_replans=0,
    )
    executor = SequenceExecutor(
        [
            OpenClawExecutionResult(
                outcome="completed",
                summary="reported complete without evidence",
            ),
            OpenClawExecutionResult(
                outcome="completed",
                summary="should not execute second node",
            ),
        ],
        auto_verify_dod=False,
    )

    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert run.status is AsyncRunStatus.BLOCKED
    assert task.status is TaskStatus.BLOCKED
    assert len(executor.requests) == 2
    assert plan.outcome_judgement is not None
    assert plan.outcome_judgement["reason_code"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_missing_evidence_after_completed_actions_blocks_without_replay(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    task_id, run_id = _seed_run(session_factory, tmp_path, key="plan-no-replay-completed")
    _replace_plan(session_factory, run_id, task_id, max_replans=1)
    executor = SequenceExecutor(
        [
            OpenClawExecutionResult(
                outcome="completed",
                summary="source collected",
                criterion_verification=(
                    CriterionVerification(
                        criterion="source collected",
                        status="verified",
                        evidence_refs=("ev_source",),
                    ),
                ),
            ),
            OpenClawExecutionResult(
                outcome="completed",
                summary="analysis completed but verification evidence is missing",
                criterion_verification=(
                    CriterionVerification(
                        criterion="source collected",
                        status="verified",
                        evidence_refs=("ev_source",),
                    ),
                ),
            ),
            OpenClawExecutionResult(
                outcome="completed",
                summary="must never replay completed action",
            ),
        ],
        auto_verify_dod=False,
    )

    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert [request.plan_node_id for request in executor.requests] == ["collect", "analyze"]
    assert run.status is AsyncRunStatus.BLOCKED
    assert task.status is TaskStatus.BLOCKED
    assert plan.revision == 1
    assert plan.outcome_judgement is not None
    assert plan.outcome_judgement["reason_code"] == "dod_evidence_missing"


@pytest.mark.asyncio
async def test_resume_at_verification_uses_persisted_evidence_without_replay(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="plan-resume-verify",
    )
    collect_evidence = ExecutionEvidence(
        id="ev_collect_done",
        node_id="collect",
        kind="result",
        summary="source collected",
        outcome="completed",
        criterion_verification=(
            {
                "criterion": "source collected",
                "status": "verified",
                "evidence_refs": ["ev_source"],
            },
        ),
    )
    analyze_evidence = ExecutionEvidence(
        id="ev_analyze_done",
        node_id="analyze",
        kind="result",
        summary="analysis complete",
        outcome="completed",
        criterion_verification=(
            {
                "criterion": "source collected",
                "status": "verified",
                "evidence_refs": ["ev_source"],
            },
            {
                "criterion": "analysis verified",
                "status": "verified",
                "evidence_refs": ["ev_analysis"],
            },
        ),
    )
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        executions=(
            PlanNodeExecution(
                node_id="collect",
                state=PlanNodeState.COMPLETED,
                attempts=1,
                evidence_ids=(collect_evidence.id,),
            ),
            PlanNodeExecution(
                node_id="analyze",
                state=PlanNodeState.COMPLETED,
                attempts=1,
                evidence_ids=(analyze_evidence.id,),
            ),
        ),
        evidence=(collect_evidence, analyze_evidence),
        budget=ExecutionBudget(max_actions=4, actions_used=2, started_at=NOW),
    )
    executor = SequenceExecutor([])

    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert executor.requests == []
    assert run.status is AsyncRunStatus.COMPLETED
    assert task.status is TaskStatus.COMPLETED
    states = {item.node_id: item.state for item in plan.node_executions}
    assert states["verify"] is PlanNodeState.COMPLETED
    assert plan.outcome_judgement is not None
    assert plan.outcome_judgement["disposition"] == "satisfied"


@pytest.mark.asyncio
async def test_elapsed_budget_blocks_before_executor_call(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    task_id, run_id = _seed_run(session_factory, tmp_path, key="plan-elapsed-budget")
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        budget=ExecutionBudget(
            max_actions=4,
            max_elapsed_seconds=1,
            started_at=NOW - timedelta(seconds=2),
        ),
    )
    executor = SequenceExecutor([])
    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)
    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "budget_exhausted"
    assert task.status is TaskStatus.BLOCKED
    assert plan.outcome_judgement["reason_code"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_zero_retry_budget_prevents_transport_retry(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    task_id, run_id = _seed_run(session_factory, tmp_path, key="plan-zero-retry")
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        max_retries=0,
    )
    executor = SequenceExecutor(
        [
            OpenClawTransportError(
                "connection_error",
                "temporary connection failure",
                retryable=True,
            )
        ]
    )
    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)
    assert len(executor.requests) == 1
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "budget_exhausted"
    assert task.status is TaskStatus.BLOCKED
    assert plan.execution_budget.retries_used == 0


@pytest.mark.asyncio
async def test_core_health_ready_uses_durable_outcome_judge(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    goal = (
        "Kiểm tra trạng thái Ánh Dương Core bằng chế độ chỉ đọc: "
        "kiểm tra /health và /ready, không sửa file, không sửa config, "
        "không restart service, rồi kết luận hệ thống có sẵn sàng hay không."
    )
    task_id, run_id = _seed_run(session_factory, tmp_path, key="plan-native-health", goal=goal)
    executor = SequenceExecutor([])

    async def probe() -> dict[str, object]:
        return {
            "health": {"http_status": 200, "status": "ok"},
            "ready": {"http_status": 200, "status": "ready", "database": "ok"},
        }

    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
        core_status_probe=probe,
    )
    assert await worker.run_once() is True
    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(TaskRepository(session), _audit(tmp_path)).get(task_id)
        plan = PlanRepository(session).get(run_id)
    assert plan is not None
    assert executor.requests == []
    assert run.status is AsyncRunStatus.COMPLETED
    assert task.status is TaskStatus.COMPLETED
    assert plan.outcome_judgement is not None
    assert plan.outcome_judgement["disposition"] == "satisfied"
    states = {item.node_id: item.state for item in plan.node_executions}
    assert states["execute"] is PlanNodeState.COMPLETED
    assert states["verify"] is PlanNodeState.COMPLETED
    assert plan.evidence and plan.evidence[0].provenance == "core"


@pytest.mark.asyncio
async def test_resume_running_node_blocks_as_uncertain_side_effect_without_replay(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    task_id, run_id = _seed_run(session_factory, tmp_path, key="plan-running-crash")
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        executions=(PlanNodeExecution(node_id="collect", state=PlanNodeState.RUNNING, attempts=1),),
    )
    executor = SequenceExecutor([])

    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "uncertain_side_effect"
    assert task.status is TaskStatus.BLOCKED
    assert plan.outcome_judgement["reason_code"] == "uncertain_side_effect"


@pytest.mark.asyncio
async def test_approval_gate_waits_for_owner_without_calling_executor(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    from app.planning.scheduler import PlanNodeScheduler

    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="plan-approval-pending",
        risk_level=2,
        approval_required=True,
    )
    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="blocked", summary="must not run")]
    )

    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "approval_required"
    assert task.status is TaskStatus.BLOCKED
    assert PlanNodeScheduler().state_for(plan, "approval") is PlanNodeState.PENDING


@pytest.mark.asyncio
async def test_approved_gate_completes_before_action_execution(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    from app.db.models import ApprovalRow
    from app.planning.scheduler import PlanNodeScheduler

    goal = "Execute approved deterministic task"
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="plan-approval-approved",
        goal=goal,
        risk_level=2,
        approval_required=True,
    )
    with session_factory() as session:
        approval = session.query(ApprovalRow).filter_by(workflow_id=run_id).one()
        approval.status = "approved"
        approval.resolved_at = NOW
        approval.resolved_by = "test-owner"
        session.commit()
    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="blocked", summary="stop after gate")]
    )
    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert len(executor.requests) == 1
    assert executor.requests[0].plan_node_id == "execute"
    assert PlanNodeScheduler().state_for(plan, "approval") is PlanNodeState.COMPLETED
    assert run.status is AsyncRunStatus.BLOCKED
    assert task.status is TaskStatus.BLOCKED


@pytest.mark.asyncio
async def test_action_budget_blocks_before_semantic_replan_revision(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    task_id, run_id = _seed_run(session_factory, tmp_path, key="plan-replan-action-budget")
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        max_replans=2,
        executions=(
            PlanNodeExecution(node_id="collect", state=PlanNodeState.COMPLETED, attempts=1),
            PlanNodeExecution(node_id="analyze", state=PlanNodeState.COMPLETED, attempts=1),
        ),
        budget=ExecutionBudget(max_actions=2, actions_used=2, started_at=NOW),
    )
    executor = SequenceExecutor([])
    _, run, task, plan = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "budget_exhausted"
    assert task.status is TaskStatus.BLOCKED
    assert plan.revision == 1
    assert plan.outcome_judgement is not None
    assert plan.outcome_judgement["reason_code"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_resume_failed_node_uses_durable_terminal_result_without_replay(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    task_id, run_id = _seed_run(session_factory, tmp_path, key="plan-failed-crash")
    failed_result = OpenClawExecutionResult(
        outcome="failed",
        summary="action failed before terminal persistence",
        error_code="agent_failed",
    )
    evidence = ExecutionEvidence(
        id="ev_failed_crash",
        node_id="collect",
        kind="result",
        summary=failed_result.summary,
        outcome="failed",
        result_payload=failed_result.model_dump(mode="json"),
        provenance="openclaw",
        created_at=NOW,
    )
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        executions=(
            PlanNodeExecution(
                node_id="collect",
                state=PlanNodeState.FAILED,
                attempts=1,
                evidence_ids=(evidence.id,),
                last_failure_class="agent_failed",
            ),
        ),
        evidence=(evidence,),
    )
    executor = SequenceExecutor([])

    _, run, task, _ = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)

    assert executor.requests == []
    assert run.status is AsyncRunStatus.FAILED
    assert run.last_error_code == "agent_failed"
    assert task.status is TaskStatus.FAILED


@pytest.mark.asyncio
async def test_resume_after_satisfied_judgement_completes_without_replay(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    task_id, run_id = _seed_run(session_factory, tmp_path, key="plan-satisfied-crash")
    result = OpenClawExecutionResult(
        outcome="completed",
        summary="durably verified before terminal persistence",
        criterion_verification=(
            CriterionVerification(
                criterion="source collected",
                status="verified",
                evidence_refs=("ev_source",),
            ),
            CriterionVerification(
                criterion="analysis verified",
                status="verified",
                evidence_refs=("ev_analysis",),
            ),
        ),
    )
    evidence = ExecutionEvidence(
        id="ev_satisfied_crash",
        node_id="analyze",
        kind="result",
        summary=result.summary,
        outcome="completed",
        criterion_verification=tuple(
            item.model_dump(mode="json") for item in result.criterion_verification
        ),
        result_payload=result.model_dump(mode="json"),
        provenance="openclaw",
        created_at=NOW,
    )
    _replace_plan(
        session_factory,
        run_id,
        task_id,
        executions=(
            PlanNodeExecution(node_id="collect", state=PlanNodeState.COMPLETED, attempts=1),
            PlanNodeExecution(
                node_id="analyze",
                state=PlanNodeState.COMPLETED,
                attempts=1,
                evidence_ids=(evidence.id,),
            ),
            PlanNodeExecution(node_id="verify", state=PlanNodeState.COMPLETED),
        ),
        evidence=(evidence,),
    )
    with session_factory() as session:
        repository = PlanRepository(session)
        plan = repository.get(run_id)
        assert plan is not None
        repository.save(
            workflow_id=run_id,
            task_id=task_id,
            plan=plan.model_copy(
                update={
                    "outcome_judgement": {
                        "disposition": "satisfied",
                        "criteria": [],
                        "reason_code": "dod_satisfied",
                        "reason": "durably satisfied",
                    }
                }
            ),
        )
        session.commit()
    executor = SequenceExecutor([])

    _, run, task, _ = await _run_and_load(session_factory, tmp_path, executor, run_id, task_id)
    assert executor.requests == []
    assert run.status is AsyncRunStatus.COMPLETED
    assert task.status is TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_no_plan_core_health_blocks_without_openclaw(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    goal = (
        "Kiểm tra /health và /ready của Ánh Dương Core, chỉ đọc, "
        "không sửa file, không sửa config, không restart service."
    )
    task_id, run_id = _seed_run(
        session_factory, tmp_path, key="plan-missing-core-health", goal=goal
    )
    with session_factory() as session:
        row = session.get(WorkflowRow, run_id)
        assert row is not None
        session.delete(row)
        session.commit()

    executor = SequenceExecutor(
        [OpenClawExecutionResult(outcome="completed", summary="must not execute")]
    )

    async def probe() -> dict[str, object]:
        return {
            "health": {"http_status": 200, "status": "ok"},
            "ready": {"http_status": 200, "status": "ready"},
        }

    worker = _worker(
        session_factory=session_factory, tmp_path=tmp_path, executor=executor,
        clock=[NOW], core_status_probe=probe
    )
    assert await worker.run_once() is True
    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(TaskRepository(session), _audit(tmp_path)).get(task_id)
    assert executor.requests == []
    assert run.status is AsyncRunStatus.BLOCKED
    assert run.last_error_code == "plan_missing"
    assert task.status is TaskStatus.BLOCKED


def test_result_from_plan_evidence_preserves_latest_terminal_outcome(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    task_id, run_id = _seed_run(
        session_factory, tmp_path, key="preserve-evidence-outcome"
    )
    failed = OpenClawExecutionResult(
        outcome="failed", summary="durable failure", error_code="agent_failed"
    )
    evidence = ExecutionEvidence(
        id="ev_failed_outcome", node_id="execute", kind="result",
        summary=failed.summary, outcome="failed",
        result_payload=failed.model_dump(mode="json"),
        provenance="openclaw", created_at=NOW,
    )
    with session_factory() as session:
        plan = PlanRepository(session).get(run_id)
        assert plan is not None
    result = AsyncTaskWorker._result_from_plan_evidence(
        plan.model_copy(update={"evidence": (evidence,)})
    )
    assert result.outcome == "failed"
    assert result.error_code == "agent_failed"


@pytest.mark.asyncio
async def test_run_attempt_exhaustion_never_schedules_planned_retry(
    session_factory: sessionmaker[Session], tmp_path
) -> None:
    task_id, run_id = _seed_run(
        session_factory, tmp_path, key="run-attempt-budget-terminal"
    )
    with session_factory() as session:
        row = AsyncTaskRepository(session).get_row(run_id)
        row.max_attempts = 1
        session.commit()
    executor = SequenceExecutor([OpenClawTransportError(
        "connection_error", "temporary", retryable=True
    )])
    worker = _worker(
        session_factory=session_factory, tmp_path=tmp_path, executor=executor, clock=[NOW]
    )
    assert await worker.run_once() is True
    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(TaskRepository(session), _audit(tmp_path)).get(task_id)
    assert run.status is AsyncRunStatus.FAILED
    assert task.status is TaskStatus.FAILED
    assert await worker.run_once() is False
    assert len(executor.requests) == 1
