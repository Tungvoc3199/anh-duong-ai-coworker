from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.approvals import ApprovalConflict, ApprovalService
from app.async_tasks import (
    AsyncRunStatus,
    AsyncTaskCreate,
    AsyncTaskPolicyGate,
    AsyncTaskRepository,
    AsyncTaskService,
)
from app.audit import AuditWriter
from app.db.base import Base
from app.db.models import ApprovalRow, ProjectRow, TaskRow, WorkflowRow
from app.openclaw import (
    OpenClawExecutionResult,
)
from app.tasks import TaskRepository, TaskService


@pytest.fixture
def session_factory(tmp_path) -> sessionmaker[Session]:
    db_path = tmp_path / "test_approvals.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_approval_service_lifecycle(session_factory: sessionmaker[Session]) -> None:
    now = datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
    with session_factory() as session:
        # Create prerequisite task & workflow rows for foreign key constraints
        task = TaskRow(
            id="task_123",
            project_id="proj_1",
            title="Test Task",
            description="Test Goal",
        )
        wf = WorkflowRow(id="wf_123", task_id="task_123", status="pending")
        session.add_all([task, wf])
        session.commit()

        service = ApprovalService(session, clock=lambda: now)
        row = service.create(
            workflow_id="wf_123",
            task_id="task_123",
            action="deploy_staging",
            risk_level=2,
            reason="Gated deployment",
            preview={"target": "staging"},
            ttl_seconds=300,
        )
        assert row.id is not None
        assert row.status == "pending"
        assert row.action_hash == ApprovalService.action_hash("deploy_staging")
        assert row.expires_at == now + timedelta(seconds=300)
        session.commit()

        # Replay / wrong action fails
        with pytest.raises(ApprovalConflict):
            service.resolve(
                row.id,
                workflow_id="wf_123",
                task_id="task_123",
                action="wrong_action",
                resolved_by="admin",
                approved=True,
            )

        # Successful resolution
        resolved = service.resolve(
            row.id,
            workflow_id="wf_123",
            task_id="task_123",
            action="deploy_staging",
            resolved_by="admin",
            approved=True,
        )
        assert resolved.status == "approved"
        assert resolved.resolved_by == "admin"
        assert resolved.resolved_at is not None
        session.commit()

        # Double resolution fails
        with pytest.raises(ApprovalConflict):
            service.resolve(
                row.id,
                workflow_id="wf_123",
                task_id="task_123",
                action="deploy_staging",
                resolved_by="admin",
                approved=True,
            )


def test_async_task_approval_resume_same_run(
    session_factory: sessionmaker[Session],
    tmp_path,
) -> None:
    audit_file = tmp_path / "audit.jsonl"
    audit_writer = AuditWriter(audit_file)
    with session_factory() as session:
        session.add(
            ProjectRow(
                id="proj_1",
                name="Project 1",
                slug="proj-1",
                path_wsl=str(tmp_path),
            )
        )
        session.commit()

        task_repo = TaskRepository(session)
        task_service = TaskService(task_repo, audit_writer)
        async_repo = AsyncTaskRepository(session, audit_writer=audit_writer)
        async_service = AsyncTaskService(
            repository=async_repo,
            task_service=task_service,
            policy_gate=AsyncTaskPolicyGate(allowed_workspace_roots=(tmp_path,)),
        )

        request = AsyncTaskCreate(
            project_id="proj_1",
            title="Approval Required Task",
            goal="Do dangerous thing",
            workspace=str(tmp_path),
            risk_level=2,
            approval_required=True,
        )
        accepted = async_service.create(request)
        assert accepted.status == AsyncRunStatus.PENDING
        run = async_repo.get(accepted.run_id)
        assert run.status == AsyncRunStatus.PENDING

        # Simulate worker claiming and blocking the run
        async_repo.claim_next(worker_id="w1", now=datetime.now(UTC), lease_seconds=60)
        async_repo.transition(run.id, AsyncRunStatus.BLOCKED, now=datetime.now(UTC))
        session.commit()

        # Find the created approval row
        approval = session.query(ApprovalRow).filter_by(workflow_id=run.id).one()
        assert approval.status == "pending"

        # Resolve approval via service
        resumed = async_service.resolve_approval(
            approval.id,
            resolved_by="operator@telegram",
            approved=True,
            action="Do dangerous thing",
        )
        assert resumed.id == approval.id
        assert resumed.status == "approved"

        # Check the run is back to pending with the SAME run_id
        resumed_run = async_repo.get(run.id)
        assert resumed_run.id == run.id
        assert resumed_run.status == AsyncRunStatus.PENDING


def test_governed_coding_worker_contract() -> None:
    from app.async_tasks.worker import AsyncTaskWorker
    from app.openclaw.models import GovernanceResult

    valid_gov = GovernanceResult(
        decision="allow",
        status="verified",
        reason="Approved and verified",
        checkpoint_id="AD-L5-05",
        production_write=False,
    )
    result_valid = OpenClawExecutionResult(
        outcome="completed",
        summary="Done",
        governance_result=valid_gov,
    )
    assert AsyncTaskWorker._completed_governance_valid(result_valid) is True

    # Missing governance result
    result_missing = OpenClawExecutionResult(
        outcome="completed",
        summary="Done",
        governance_result=None,
    )
    assert AsyncTaskWorker._completed_governance_valid(result_missing) is False

    # Invalid status/decision
    invalid_gov = GovernanceResult(
        decision="deny",
        status="denied",
        reason="Forbidden",
    )
    result_invalid = OpenClawExecutionResult(
        outcome="completed",
        summary="Done",
        governance_result=invalid_gov,
    )
    assert AsyncTaskWorker._completed_governance_valid(result_invalid) is False

