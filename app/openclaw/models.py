from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OpenClawExecutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    run_id: str
    attempt: int = Field(ge=1)
    idempotency_key: str
    project_id: str
    goal: str
    mode: Literal["quick", "build"]
    workspace: str | None = None
    constraints: tuple[str, ...] = ()


class OpenClawExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Literal["completed", "blocked", "failed"]
    summary: str
    artifacts: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    external_run_id: str | None = None


class OpenClawTransportError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        uncertain_side_effect: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.uncertain_side_effect = uncertain_side_effect
        self.status_code = status_code
