from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.async_tasks.worker import (
    merge_governed_test_evidence,
    verify_governed_tests,
)
from app.capabilities import CapabilityKind
from app.orchestration.coding_governance import (
    CodingAssignment,
    GovernanceContractError,
    GovernedTestEvidence,
    GovernedTestRuntime,
)
from app.orchestration.models import CoreRequest
from tests.unit.test_core_request_pipeline_behavior import (
    ProjectReader,
    _pipeline,
    _project,
)

EXACT_REQUEST = (
    "Tạo app/multiply.py với hàm multiply(a, b). "
    "Tạo tests/unit/test_multiply.py. Chạy test tương ứng. "
    "Chỉ được sửa hai file trên. Không deploy; không sửa DB, config, "
    "provider hoặc dependency. Checkpoint: AD-L5-05."
)


def _assignment(
    tmp_path: Path,
    executable: Path | None = None,
    *,
    argv: tuple[str, ...] = (
        "-m",
        "pytest",
        "tests/unit/test_multiply.py",
        "-q",
    ),
) -> CodingAssignment:
    workspace = tmp_path / "anh-duong-core.worktrees" / "ad-l5-05"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".git").write_text(
        "gitdir: /repo/.git/worktrees/ad-l5-05\n",
        encoding="utf-8",
    )
    return CodingAssignment(
        checkpoint_id="AD-L5-05",
        correlation_id="exact-reproduction",
        workspace=str(workspace),
        manifest_digest="a" * 64,
        allowed_paths=("app/multiply.py", "tests/unit/test_multiply.py"),
        reviewer_required=True,
        approval_required=False,
        max_semantic_repair_rounds=2,
        test_runtime=GovernedTestRuntime(
            executable=str(executable or workspace / ".venv" / "bin" / "python"),
            argv=argv,
            timeout_seconds=120,
            allow_fallback=False,
        ),
    )


def _make_executable(assignment: CodingAssignment) -> Path:
    assert assignment.test_runtime is not None
    executable = Path(assignment.test_runtime.executable)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o700)
    return executable


def test_exact_vietnamese_request_prepares_governed_code_assignment() -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(text=EXACT_REQUEST, request_id="exact-reproduction")
    )

    assert prepared.capability_decision.capability is CapabilityKind.CODE_OPERATION
    assert prepared.workflow is not None
    assignment = prepared.workflow.governed_coding
    assert assignment is not None
    assert assignment.test_runtime is not None
    assert assignment.test_runtime.executable == str(
        Path(assignment.workspace) / ".venv" / "bin" / "python"
    )
    assert assignment.test_runtime.allow_fallback is False
    assert assignment.test_runtime.argv == ("-m", "pytest", "tests", "-q")


def test_core_verification_uses_exact_argv_runtime_and_worktree(
    tmp_path: Path,
) -> None:
    assignment = _assignment(tmp_path)
    executable = _make_executable(assignment)
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="1 passed in 0.01s\n", stderr=""
    )

    with patch("app.async_tasks.worker.subprocess.run", return_value=completed) as run:
        evidence = verify_governed_tests(assignment)

    run.assert_called_once_with(
        [str(executable), "-m", "pytest", "tests/unit/test_multiply.py", "-q"],
        cwd=assignment.workspace,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        shell=False,
    )
    assert evidence.passed == 1
    assert evidence.return_code == 0


@pytest.mark.parametrize(
    "argv",
    [
        ("-m", "pip", "install", "pytest"),
        ("-m", "arbitrary", "tests/unit/test_multiply.py"),
        ("-m", "pytest", "app/multiply.py"),
        ("-m", "pytest", "tests/unit/other.py"),
        ("-m", "pytest", "../tests/unit/test_multiply.py"),
        ("-m", "pytest", "tests/unit/test_multiply.py", "--collect-only"),
    ],
)
def test_core_verification_rejects_unapproved_argv(
    tmp_path: Path,
    argv: tuple[str, ...],
) -> None:
    assignment = _assignment(tmp_path, argv=argv)
    _make_executable(assignment)

    with patch("app.async_tasks.worker.subprocess.run") as run:
        with pytest.raises(GovernanceContractError):
            verify_governed_tests(assignment)
    run.assert_not_called()


def test_core_verification_rejects_non_workspace_venv(tmp_path: Path) -> None:
    executable = tmp_path / "other" / ".venv" / "bin" / "python"
    assignment = _assignment(tmp_path, executable)
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o700)

    with pytest.raises(GovernanceContractError, match="workspace venv"):
        verify_governed_tests(assignment)


@pytest.mark.parametrize(
    ("failure", "completed"),
    [
        (OSError("exec failed"), None),
        (subprocess.TimeoutExpired(["python"], 120), None),
        (None, SimpleNamespace(returncode=1, stdout="1 passed in 0.01s", stderr="")),
        (None, SimpleNamespace(returncode=0, stdout="no tests ran", stderr="")),
        (
            None,
            SimpleNamespace(
                returncode=0,
                stdout="1 passed in 0.01s\nattacker-controlled trailing output",
                stderr="",
            ),
        ),
    ],
)
def test_core_verification_fails_closed_for_execution_and_spoofing(
    tmp_path: Path,
    failure: BaseException | None,
    completed: object,
) -> None:
    assignment = _assignment(tmp_path)
    _make_executable(assignment)

    with patch(
        "app.async_tasks.worker.subprocess.run",
        side_effect=failure,
        return_value=completed,
    ):
        with pytest.raises(GovernanceContractError):
            verify_governed_tests(assignment)

def test_core_evidence_merge_preserves_reported_verification() -> None:
    evidence = GovernedTestEvidence(
        executable="/workspace/.venv/bin/python",
        argv=("-m", "pytest", "tests", "-q"),
        workspace="/workspace",
        return_code=0,
        passed=7,
    )

    merged = merge_governed_test_evidence(
        {"review": {"outcome": "PASS"}, "audit_id": "audit-1"},
        evidence,
    )

    assert merged["review"] == {"outcome": "PASS"}
    assert merged["audit_id"] == "audit-1"
    assert merged["core_governed_tests"] == evidence.model_dump(mode="json")


def test_core_evidence_merge_preserves_tuple_default_under_reported() -> None:
    evidence = GovernedTestEvidence(
        executable="/workspace/.venv/bin/python",
        argv=("-m", "pytest", "tests", "-q"),
        workspace="/workspace",
        return_code=0,
        passed=7,
    )

    merged = merge_governed_test_evidence((), evidence)

    assert merged["reported"] == ()
    assert merged["core_governed_tests"] == evidence.model_dump(mode="json")
