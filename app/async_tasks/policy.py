from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.async_tasks.models import AsyncTaskCreate, AsyncTaskMode
from app.policy.path_scope import WorkspacePathPolicy


SAFE_STEPS_WITHOUT_APPROVAL: tuple[str, ...] = (
    "web_search_read",
    "summarize",
    "analysis",
    "draft_content",
    "local_file_read",
    "read_only_checks",
)
HARD_APPROVAL_GATED_STEPS: tuple[str, ...] = (
    "destructive",
    "publish",
    "send_external",
    "secret_or_security_boundary",
    "unapproved_cost",
)
STEP_LEVEL_EXECUTION_CONSTRAINTS: tuple[str, ...] = (
    "complete_safe_steps_before_approval_gate",
    "hard_gate_publish_send_external_destructive_secret_cost",
)


class AsyncPolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason_code: str
    message: str


class AsyncTaskPolicyGate:
    def __init__(
        self,
        allowed_workspace_roots: tuple[Path, ...],
    ) -> None:
        self._path_policy = WorkspacePathPolicy(
            allowed_workspace_roots
        )

    def evaluate(
        self,
        request: AsyncTaskCreate,
    ) -> AsyncPolicyDecision:
        if request.risk_level >= 4:
            return AsyncPolicyDecision(
                allowed=False,
                reason_code="forbidden",
                message="Risk level 4 actions are forbidden.",
            )

        if (
            request.mode is AsyncTaskMode.BUILD
            and request.workspace is None
        ):
            return AsyncPolicyDecision(
                allowed=False,
                reason_code="workspace_required",
                message="Build mode requires an explicit workspace.",
            )

        if request.workspace is not None:
            path_result = self._path_policy.check(
                Path(request.workspace)
            )
            if not path_result.allowed:
                return AsyncPolicyDecision(
                    allowed=False,
                    reason_code="workspace_denied",
                    message=path_result.reason,
                )

        if request.approval_required or request.risk_level >= 2:
            return AsyncPolicyDecision(
                allowed=True,
                reason_code="allowed_with_step_gates",
                message=(
                    "Request is accepted for step-level execution: safe "
                    "steps may run, approval-gated steps must stop."
                ),
            )

        return AsyncPolicyDecision(
            allowed=True,
            reason_code="allowed",
            message="Request is allowed for asynchronous execution.",
        )
