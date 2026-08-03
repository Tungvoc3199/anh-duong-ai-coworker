from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PersonaSnapshot(BaseModel):
    """Immutable persona snapshot attached to a workflow."""

    model_config = ConfigDict(frozen=True)

    version: str = Field(min_length=1)
    language: str = "vi"
    relationship: str = "em-anh"
    tone: str = "direct"
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_order: tuple[str, ...]
    files: dict[str, str]
    combined_content: str
