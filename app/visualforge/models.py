from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VisualPromptSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    template: str = Field(min_length=1)
    adapter: str = "gpt-image"
    required_text: str = ""
    aspect_ratio: str = ""


class VisualForgeCompiledPrompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    required_text: str = ""
    provenance_notes: tuple[str, ...] = ()
    sections: dict[str, str] = Field(default_factory=dict)
