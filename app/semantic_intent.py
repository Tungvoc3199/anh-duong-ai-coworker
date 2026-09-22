from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.capabilities.models import CapabilityDecision, CapabilityKind
from app.routing.models import FastRoute, RouteDecision
from app.visual_interaction import (
    VisualImageRole,
    VisualImageSource,
    VisualInteractionContract,
    VisualOperation,
    VisualOutput,
    VisualSideEffect,
)


class IntentSpeechAct(StrEnum):
    ASK = "ask"
    INFORM = "inform"
    ACTION_REQUEST = "action_request"
    PROHIBITION = "prohibition"
    CONFIRMATION = "confirmation"


class IntentDomain(StrEnum):
    CONVERSATION = "conversation"
    VISUAL = "visual"
    EXTERNAL_COMMUNICATION = "external_communication"
    FILE = "file"
    CODE = "code"
    SYSTEM = "system"
    MEMORY = "memory"
    CORE = "core"
    PLANNING = "planning"
    WEB = "web"
    UNKNOWN = "unknown"


class IntentAction(StrEnum):
    NONE = "none"
    DISCUSS_EDIT = "discuss_edit"
    ANALYZE = "analyze"
    COMPARE = "compare"
    GENERATE = "generate"
    EDIT = "edit"
    COMPOSE_PROMPT = "compose_prompt"
    SEND = "send"
    PUBLISH = "publish"
    SAVE = "save"
    DELETE = "delete"
    READ = "read"
    SEARCH = "search"
    PLAN = "plan"
    EXECUTE = "execute"
    STATUS = "status"


class IntentTarget(StrEnum):
    NONE = "none"
    IMAGE = "image"
    MEMORY = "memory"
    CORE = "core"
    PROJECT = "project"
    TASK = "task"
    FILE = "file"
    CODE = "code"
    SYSTEM = "system"
    EXTERNAL_RECIPIENT = "external_recipient"
    URL = "url"
    OTHER = "other"


class IntentAuthorization(StrEnum):
    NONE = "none"
    EXPLICIT = "explicit"
    PROHIBITED = "prohibited"


class VisualCompilerType(StrEnum):
    PORTRAIT_PERSONA = "portrait_persona"
    PRODUCT = "product"
    POSTER_TEXT = "poster_text"
    REFERENCE_EDIT = "reference_edit"


class SemanticIntentFrame(BaseModel):
    """Whole-utterance meaning selected before route/capability policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    speech_act: IntentSpeechAct
    domain: IntentDomain
    action: IntentAction
    target: IntentTarget = IntentTarget.NONE
    requested_execution: bool
    authorization: IntentAuthorization
    recipient: str | None = Field(default=None, max_length=512)
    channel: str | None = Field(default=None, max_length=128)
    uses_contextual_visual: bool = False
    visual_compiler_type: VisualCompilerType | None = None
    visual_identity_lock: bool = False
    visual_preserve_unmentioned: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_execution_authority(self) -> SemanticIntentFrame:
        if self.authorization is IntentAuthorization.PROHIBITED and self.requested_execution:
            raise ValueError("prohibited intent cannot request execution")
        read_only_actions = {
            IntentAction.NONE,
            IntentAction.DISCUSS_EDIT,
            IntentAction.ANALYZE,
            IntentAction.COMPARE,
            IntentAction.READ,
            IntentAction.SEARCH,
            IntentAction.STATUS,
        }
        if self.requested_execution and self.action in read_only_actions:
            raise ValueError("read-only intent cannot request workflow execution")
        if self.requested_execution:
            if self.speech_act is not IntentSpeechAct.ACTION_REQUEST:
                raise ValueError("execution requires an action_request speech act")
            if self.authorization is not IntentAuthorization.EXPLICIT:
                raise ValueError("execution requires explicit current-turn authorization")
        if self.visual_compiler_type is not None:
            if (
                self.domain is not IntentDomain.VISUAL
                or self.action not in {IntentAction.GENERATE, IntentAction.EDIT}
                or not self.requested_execution
            ):
                raise ValueError("visual compiler contract requires executable visual intent")
            if (
                self.visual_compiler_type is VisualCompilerType.REFERENCE_EDIT
                and self.action is not IntentAction.EDIT
            ):
                raise ValueError("reference_edit compiler requires edit intent")
        return self


_EXPLICIT_HTTP_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\"']+")
_EXPLICIT_URL_TRAILING_PUNCTUATION = ".,;:!?)]}"


def _has_explicit_http_url(text: str) -> bool:
    """Return True only for a structurally valid explicit http(s) URL in this turn."""

    for match in _EXPLICIT_HTTP_URL_RE.finditer(text):
        candidate = match.group(0).rstrip(_EXPLICIT_URL_TRAILING_PUNCTUATION)
        if not candidate:
            continue
        parsed = urlsplit(candidate)
        if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc:
            return True
    return False


def normalize_explicit_url_read_intent(
    frame: SemanticIntentFrame,
    *,
    raw_instruction: str,
) -> SemanticIntentFrame:
    """Anchor explicit current-turn URLs to read-only web intent after semantic parsing.

    This is a narrow structural normalization, not keyword routing. It never overrides
    prohibitions or any intent that already requests a side effect/execution.
    """

    if not _has_explicit_http_url(raw_instruction):
        return frame
    if frame.requested_execution or frame.authorization is IntentAuthorization.PROHIBITED:
        return frame
    if frame.domain not in {IntentDomain.CONVERSATION, IntentDomain.UNKNOWN}:
        return frame
    if frame.action not in {
        IntentAction.NONE,
        IntentAction.ANALYZE,
        IntentAction.COMPARE,
        IntentAction.READ,
        IntentAction.SEARCH,
    }:
        return frame

    anchored_action = (
        IntentAction.READ if frame.action is IntentAction.NONE else frame.action
    )
    return frame.model_copy(
        update={
            "domain": IntentDomain.WEB,
            "action": anchored_action,
            "target": IntentTarget.URL,
            "rationale": (
                "Explicit current-turn http/https URL anchors this read-only intent "
                "to web content."
            ),
        }
    )


def _visual_contract(
    frame: SemanticIntentFrame,
    *,
    raw_instruction: str,
    image_source: VisualImageSource,
    reference_image: str | None,
) -> VisualInteractionContract | None:
    has_visual = frame.domain is IntentDomain.VISUAL or image_source is not VisualImageSource.NONE
    if not has_visual:
        return None

    concrete = image_source not in {VisualImageSource.NONE, VisualImageSource.AMBIGUOUS}
    if frame.requested_execution:
        operation = {
            IntentAction.GENERATE: VisualOperation.GENERATE,
            IntentAction.EDIT: VisualOperation.EDIT,
            IntentAction.SEND: VisualOperation.EXTERNAL_ACTION,
            IntentAction.PUBLISH: VisualOperation.EXTERNAL_ACTION,
            IntentAction.SAVE: VisualOperation.FILE_ACTION,
            IntentAction.DELETE: VisualOperation.FILE_ACTION,
        }.get(frame.action, VisualOperation.CONVERSE)
    else:
        operation = {
            IntentAction.COMPARE: VisualOperation.COMPARE,
            IntentAction.ANALYZE: VisualOperation.ANALYZE,
            IntentAction.DISCUSS_EDIT: VisualOperation.ANALYZE,
            IntentAction.STATUS: VisualOperation.ANALYZE,
        }.get(frame.action, VisualOperation.CONVERSE)

    if operation in {VisualOperation.ANALYZE, VisualOperation.COMPARE, VisualOperation.CONVERSE}:
        output = VisualOutput.TEXT
    elif operation in {VisualOperation.GENERATE, VisualOperation.EDIT}:
        output = VisualOutput.IMAGE
    elif operation is VisualOperation.FILE_ACTION:
        output = VisualOutput.FILE
    else:
        output = VisualOutput.EXTERNAL_EFFECT

    role: VisualImageRole | None = None
    if concrete:
        if operation in {
            VisualOperation.ANALYZE,
            VisualOperation.COMPARE,
            VisualOperation.CONVERSE,
        }:
            role = VisualImageRole.EVIDENCE
        elif operation is VisualOperation.EDIT:
            role = VisualImageRole.EDIT_TARGET

    side_effect = VisualSideEffect.NONE
    if operation is VisualOperation.EXTERNAL_ACTION:
        side_effect = (
            VisualSideEffect.PUBLISH
            if frame.action is IntentAction.PUBLISH
            else VisualSideEffect.SEND
        )
    elif operation is VisualOperation.FILE_ACTION:
        side_effect = (
            VisualSideEffect.DELETE
            if frame.action is IntentAction.DELETE
            else VisualSideEffect.SAVE
        )

    needs_target = operation in {
        VisualOperation.ANALYZE,
        VisualOperation.COMPARE,
        VisualOperation.EDIT,
    }
    clarification_required = needs_target and not concrete

    return VisualInteractionContract(
        raw_instruction=raw_instruction,
        operation=operation,
        image_role=role,
        image_source=image_source,
        output=output,
        side_effect=side_effect,
        reference_image=reference_image,
        clarification_required=clarification_required,
    )


def _read_only_decision(
    frame: SemanticIntentFrame,
    visual: VisualInteractionContract | None,
) -> tuple[RouteDecision, CapabilityDecision]:
    if frame.domain is IntentDomain.MEMORY and frame.action in {
        IntentAction.READ,
        IntentAction.SEARCH,
    }:
        route = RouteDecision(
            route=FastRoute.MEMORY,
            rule_id="routing.semantic.memory",
            reason="Whole-utterance intent requests read-only memory retrieval.",
        )
        capability = CapabilityDecision(
            capability=CapabilityKind.MEMORY_SEARCH,
            source_route=FastRoute.MEMORY,
            reason_code="capability.semantic.memory_search",
            matched_signals=(f"semantic:{frame.action.value}",),
        )
        return route, capability

    if frame.domain is IntentDomain.WEB and frame.action in {
        IntentAction.READ,
        IntentAction.SEARCH,
        IntentAction.ANALYZE,
        IntentAction.COMPARE,
    }:
        route = RouteDecision(
            route=FastRoute.WORKFLOW,
            rule_id="routing.semantic.web_read",
            reason="Whole-utterance intent requests read-only web execution.",
        )
        capability = CapabilityDecision(
            capability=CapabilityKind.WEB_SEARCH_READ,
            source_route=FastRoute.WORKFLOW,
            reason_code="capability.semantic.web_search_read",
            matched_signals=(
                f"semantic:{frame.action.value}",
                f"semantic:target:{frame.target.value}",
            ),
        )
        return route, capability

    if frame.domain is IntentDomain.CORE and frame.action in {
        IntentAction.READ,
        IntentAction.STATUS,
    }:
        route = RouteDecision(
            route=FastRoute.CORE_READ,
            rule_id="routing.semantic.core_read",
            reason="Whole-utterance intent requests read-only Core state.",
        )
        capability_kind = {
            IntentTarget.PROJECT: CapabilityKind.PROJECT_READ,
            IntentTarget.TASK: CapabilityKind.TASK_READ,
        }.get(frame.target, CapabilityKind.CORE_STATUS_READ)
        capability = CapabilityDecision(
            capability=capability_kind,
            source_route=FastRoute.CORE_READ,
            reason_code=f"capability.semantic.{capability_kind.value}",
            matched_signals=(
                f"semantic:{frame.action.value}",
                f"semantic:target:{frame.target.value}",
            ),
        )
        return route, capability

    route = RouteDecision(
        route=FastRoute.DIRECT,
        rule_id="routing.semantic.read_only",
        reason="Whole-utterance intent does not authorize execution.",
    )
    visual_read = (
        visual is not None
        and visual.operation in {VisualOperation.ANALYZE, VisualOperation.COMPARE}
        and not visual.clarification_required
    )
    capability = CapabilityDecision(
        capability=(
            CapabilityKind.VISUAL_ANALYSIS
            if visual_read
            else CapabilityKind.CONVERSATIONAL_RESPONSE
        ),
        source_route=FastRoute.DIRECT,
        reason_code=(
            "capability.semantic.visual_analysis"
            if visual_read
            else "capability.semantic.conversation"
        ),
        matched_signals=(f"semantic:{frame.action.value}",),
    )
    return route, capability


def decisions_from_intent_frame(
    frame: SemanticIntentFrame,
    *,
    raw_instruction: str,
    image_source: VisualImageSource = VisualImageSource.NONE,
    reference_image: str | None = None,
) -> tuple[RouteDecision, CapabilityDecision, VisualInteractionContract | None]:
    """Project semantic meaning into route/capability contracts."""

    visual = _visual_contract(
        frame,
        raw_instruction=raw_instruction,
        image_source=image_source,
        reference_image=reference_image,
    )

    if not frame.requested_execution:
        route, capability = _read_only_decision(frame, visual)
        return route, capability, visual

    if frame.action in {IntentAction.SEND, IntentAction.PUBLISH}:
        capability_kind = CapabilityKind.EXTERNAL_COMMUNICATION
    elif frame.action in {IntentAction.GENERATE, IntentAction.EDIT}:
        capability_kind = CapabilityKind.VISUAL_IMAGE_GENERATE
    elif frame.action is IntentAction.COMPOSE_PROMPT:
        capability_kind = CapabilityKind.VISUAL_PROMPT_COMPOSE
    elif frame.domain is IntentDomain.FILE:
        capability_kind = CapabilityKind.FILE_OPERATION
    elif frame.domain is IntentDomain.CODE:
        capability_kind = CapabilityKind.CODE_OPERATION
    elif frame.domain is IntentDomain.SYSTEM or (
        frame.domain is IntentDomain.CORE
        and frame.action is IntentAction.EXECUTE
        and frame.target is IntentTarget.CORE
    ):
        capability_kind = CapabilityKind.SYSTEM_OPERATION
    elif frame.domain is IntentDomain.PLANNING:
        capability_kind = CapabilityKind.PLANNING
    else:
        capability_kind = CapabilityKind.UNKNOWN_WORKFLOW

    route = RouteDecision(
        route=FastRoute.WORKFLOW,
        rule_id="routing.semantic.execution",
        reason="Whole-utterance intent explicitly requests execution.",
    )
    capability = CapabilityDecision(
        capability=capability_kind,
        source_route=FastRoute.WORKFLOW,
        reason_code=f"capability.semantic.{capability_kind.value}",
        matched_signals=(
            f"semantic:{frame.action.value}",
            "semantic:explicit_execution",
        ),
    )
    return route, capability, visual
