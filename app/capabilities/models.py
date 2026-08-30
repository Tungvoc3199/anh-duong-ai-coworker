from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.routing.models import FastRoute


class CapabilityKind(StrEnum):
    CONVERSATIONAL_RESPONSE = "conversational_response"
    MEMORY_SEARCH = "memory_search"
    PROJECT_READ = "project_read"
    TASK_READ = "task_read"
    CORE_STATUS_READ = "core_status_read"
    PLANNING = "planning"
    VISUAL_PROMPT_COMPOSE = "visual_prompt_compose"
    FILE_OPERATION = "file_operation"
    CODE_OPERATION = "code_operation"
    EXTERNAL_COMMUNICATION = "external_communication"
    SYSTEM_OPERATION = "system_operation"
    UNKNOWN_WORKFLOW = "unknown_workflow"


class CapabilityDecision(BaseModel):
    """Immutable classification result without Policy or Approval authority."""

    model_config = ConfigDict(frozen=True)

    capability: CapabilityKind
    source_route: FastRoute
    reason_code: str = Field(min_length=1)
    matched_signals: tuple[str, ...]

