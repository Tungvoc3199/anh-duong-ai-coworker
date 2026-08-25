from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


def _git(base: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=base,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )


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


def test_governed_coding_worker_contract(tmp_path: Path) -> None:
    """Governed coding runs fail closed via the canonical completion gate.

    The reconstruction preserves canonical main's ``CodingResultContract``
    governance contract and ``validate_coding_completion`` gate. A completed
    governed coding run must carry a merge-ready result that matches the
    assigned coding checkpoint, otherwise the run fails closed.
    """
    from app.orchestration.coding_governance import (
        CodingAssignment,
        CodingResultContract,
        FailureClassification,
        GovernanceContractError,
        ReviewerOutcome,
        validate_coding_completion,
    )

    # Build a real isolated git worktree so the canonical worktree-identity
    # gate in validate_coding_completion has a legitimate workspace to pass.
    main = tmp_path / "main"
    (main / "app").mkdir(parents=True)
    (main / "app" / "example.py").write_text("x = 1\n", encoding="utf-8")
    _git(main, "init", "-q")
    _git(main, "config", "user.email", "t@example.com")
    _git(main, "config", "user.name", "test")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "init")
    main_wt = main / "wt"
    _git(main, "worktree", "add", str(main_wt), "-b", "wt1")
    workspace = str(main_wt)

    assignment = CodingAssignment(
        checkpoint_id="AD-L5-05",
        correlation_id="req_exec_1",
        workspace=workspace,
        manifest_digest="b" * 64,
        allowed_paths=("app/", "tests/"),
        reviewer_required=True,
        approval_required=False,
        max_semantic_repair_rounds=2,
    )

    def _result(**overrides: object) -> CodingResultContract:
        fields: dict[str, object] = {
            "checkpoint_id": assignment.checkpoint_id,
            "correlation_id": assignment.correlation_id,
            "status": "MERGE_READY",
            "classification": FailureClassification.DELTA_FAILURE,
            "manifest_digest": assignment.manifest_digest,
            "files_changed": ("app/example.py",),
            "commands_run": ("pytest -q",),
            "tests": (),
            "model": "router/model",
            "provider": "router",
            "profile": "CE-2",
            "duration_ms": 100,
            "error_code": None,
            "production_write": False,
            "service_restart": False,
            "database_write": False,
            "reviewer_outcome": ReviewerOutcome.PASS,
            "reviewer_read_only": True,
            "approval_granted": False,
            "repair_round": 0,
        }
        fields.update(overrides)
        return CodingResultContract(**fields)

    # A fully valid result in a legitimate isolated worktree passes the gate.
    valid = _result()
    assert validate_coding_completion(assignment, valid) is valid

    # Missing merge-readiness fails closed.
    with pytest.raises(GovernanceContractError):
        validate_coding_completion(
            assignment,
            _result(status="REJECTED"),
        )

    # Manifest identity mismatch fails closed.
    with pytest.raises(GovernanceContractError):
        validate_coding_completion(
            assignment,
            _result(manifest_digest="c" * 64),
        )

    # Forbidden side effects fail closed.
    with pytest.raises(GovernanceContractError):
        validate_coding_completion(
            assignment,
            _result(production_write=True),
        )

    # Out-of-scope changed paths fail closed.
    with pytest.raises(GovernanceContractError):
        validate_coding_completion(
            assignment,
            _result(files_changed=("secrets/pwned.txt",)),
        )

    # Completed result with an OpenClawExecutionResult is also valid.
    valid_exec = OpenClawExecutionResult(
        outcome="completed",
        summary="Done",
        governance_result=valid,
    )
    assert isinstance(valid_exec.governance_result, CodingResultContract)

