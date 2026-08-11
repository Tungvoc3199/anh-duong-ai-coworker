from pathlib import Path

from app.async_tasks import (
    AsyncTaskCreate,
    AsyncTaskMode,
    AsyncTaskPolicyGate,
)


def _gate(root: Path) -> AsyncTaskPolicyGate:
    return AsyncTaskPolicyGate((root,))


def _request(root: Path) -> AsyncTaskCreate:
    return AsyncTaskCreate(
        project_id="proj_1",
        title="Build runner",
        goal="Implement the worker",
        mode=AsyncTaskMode.BUILD,
        risk_level=1,
        workspace=str(root / "project"),
        source_channel="api",
    )


def test_safe_build_inside_allowlist_is_allowed(
    tmp_path: Path,
) -> None:
    decision = _gate(tmp_path).evaluate(_request(tmp_path))

    assert decision.allowed is True
    assert decision.reason_code == "allowed"


def test_risk_two_is_accepted_for_step_level_execution(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path).model_copy(
        update={"risk_level": 2}
    )

    decision = _gate(tmp_path).evaluate(request)

    assert decision.allowed is True
    assert decision.reason_code == "allowed_with_step_gates"


def test_explicit_approval_requirement_is_accepted_for_safe_prefix(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path).model_copy(
        update={"approval_required": True}
    )

    decision = _gate(tmp_path).evaluate(request)

    assert decision.allowed is True
    assert decision.reason_code == "allowed_with_step_gates"


def test_build_without_workspace_is_blocked(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path).model_copy(
        update={"workspace": None}
    )

    decision = _gate(tmp_path).evaluate(request)

    assert decision.allowed is False
    assert decision.reason_code == "workspace_required"


def test_workspace_outside_allowlist_is_blocked(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path).model_copy(
        update={"workspace": "/etc"}
    )

    decision = _gate(tmp_path).evaluate(request)

    assert decision.allowed is False
    assert decision.reason_code == "workspace_denied"


def test_forbidden_risk_still_blocks_task_create(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path).model_copy(
        update={"risk_level": 4}
    )

    decision = _gate(tmp_path).evaluate(request)

    assert decision.allowed is False
    assert decision.reason_code == "forbidden"
