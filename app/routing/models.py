from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FastRoute(StrEnum):
    DIRECT = "direct"
    MEMORY = "memory"
    CORE_READ = "core_read"
    WORKFLOW = "workflow"


class RouteDecision(BaseModel):
    """Immutable routing result; safety approval remains a Policy concern."""

    model_config = ConfigDict(frozen=True)

    route: FastRoute
    rule_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
