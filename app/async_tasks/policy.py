from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.async_tasks.models import AsyncTaskCreate, AsyncTaskMode
from app.policy.path_scope import WorkspacePathPolicy


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

        if request.approval_required or request.risk_level >= 2:
            return AsyncPolicyDecision(
                allowed=False,
                reason_code="approval_required",
                message=(
                    "This action requires approval and is blocked "
                    "in Async Task Runner v1."
                ),
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

        return AsyncPolicyDecision(
            allowed=True,
            reason_code="allowed",
            message="Request is allowed for asynchronous execution.",
        )
