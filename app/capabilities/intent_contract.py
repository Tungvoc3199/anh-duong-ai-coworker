from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class VisualPurpose(StrEnum):
    SOCIAL_CONTENT = "social_content"


class VisualDelivery(StrEnum):
    NONE = "none"
    SOURCE_CHANNEL = "source_channel"


class VisualExternalEffect(StrEnum):
    PUBLISH = "publish_external"
    THIRD_PARTY_SEND = "send_third_party"
    EXTERNAL_CALL = "external_call"


@dataclass(frozen=True)
class VisualIntentContract:
    """Semantic roles for a visual request; carries no policy authority."""

    purpose: tuple[VisualPurpose, ...]
    delivery: VisualDelivery
    external_effects: tuple[VisualExternalEffect, ...]
    side_effect_text: str

    @property
    def external_signals(self) -> tuple[str, ...]:
        return tuple(f"visual:effect:{effect.value}" for effect in self.external_effects)


_SOCIAL = r"(?:facebook|fb|instagram|ig|tiktok|zalo|social\s+media)"
_PUBLISH = r"(?:dang|post|publish|upload|up|share|chia\s+se)"
_SOURCE_PRONOUN = r"(?:anh|toi|minh|me|myself)"

_PURPOSE_PATTERNS = (
    re.compile(rf"\bde\s+(?:{_SOURCE_PRONOUN}\s+(?:tu\s+)?)?{_PUBLISH}\s+(?:len\s+)?{_SOCIAL}\b"),
    re.compile(rf"\bto\s+{_PUBLISH}\s+(?:(?:on|to)\s+)?{_SOCIAL}\b"),
    re.compile(rf"\bfor\s+(?:(?:my|a|an|the)\s+)?{_SOCIAL}\s+(?:post|content)\b"),
    re.compile(
        rf"\bfor\s+(?:posting\s+on\s+{_SOCIAL}|use\s+in\s+(?:(?:a|an)\s+)?{_SOCIAL}\s+(?:post|content))\b"
    ),
    re.compile(rf"\b(?:dung\s+cho|cho)\s+(?:(?:bai|noi\s+dung)\s+)?(?:dang\s+)?{_SOCIAL}\b"),
    re.compile(rf"\bde\s+lam\s+(?:noi\s+dung|content)\s+{_SOCIAL}\b"),
    re.compile(rf"\bcho\s+(?:noi\s+dung|content)\s+{_SOCIAL}\b"),
    re.compile(rf"\b(?:dung|su\s+dung)\s+(?:lam\s+)?(?:noi\s+dung|content)\s+{_SOCIAL}\b"),
    re.compile(rf"\bintended\s+for(?:\s+use\s+in)?\s+(?:(?:a|an)\s+)?{_SOCIAL}(?:\s+post)?\b"),
)


_OWNER_PUBLISH_PURPOSE = re.compile(
    rf"\b(?:anh|toi|minh)\s+(?:(?:se|tu)\s+)*(?:{_PUBLISH})"
    rf"(?:\s+(?:no|anh|hinh|image|it))?\s+(?:len\s+)?{_SOCIAL}\b|"
    rf"\b(?:i\s+will|i\s+ll)\s+{_PUBLISH}(?:\s+(?:it|the\s+image))?"
    rf"\s+(?:(?:on|to)\s+)?{_SOCIAL}\b"
)
_NON_AGENT_PURPOSE = re.compile(
    rf"\bde\s+(?!(?:em|ban|bot|anh\s+duong|you)\b)(?:[a-z0-9_]+\s+){{1,3}}"
    rf"(?:tu\s+)?{_PUBLISH}\s+(?:len\s+)?{_SOCIAL}\b"
)

_AGENTIVE_PUBLISH = re.compile(
    rf"\b(?:for\s+you\s+to\s+|want\s+you\s+to\s+|need\s+you\s+to\s+|ask\s+you\s+to\s+|"
    rf"have\s+you\s+|de\s+em\s+|cho\s+em\s+|muon\s+em\s+|nho\s+em\s+|bao\s+em\s+){_PUBLISH}\b"
)

_THIRD_PARTY_PUBLISH = re.compile(
    rf"\b(?:ask|have|tell)\s+(?!you\b)[a-z0-9_]+\s+to\s+{_PUBLISH}\b[^.;!?\n]*\b{_SOCIAL}\b|"
    rf"\b(?:nho|bao)\s+(?!em\b|anh\b|toi\b|minh\b)[a-z0-9_]+\s+{_PUBLISH}\b[^.;!?\n]*\b{_SOCIAL}\b"
)
_IMMEDIATE_COMMAND = re.compile(
    r"\b(?:lam\s+ngay|thuc\s+hien\s+ngay|do\s+it\s+now|please\s+do\s+it\s+now)\b"
)
_QUOTED_COPY = re.compile(r'["“]([^"”]*)["”]')
_TIMING = re.compile(
    r"\b(?:now|right\s+now|asap|tomorrow|tonight|at\s+noon|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?|"
    r"bay\s+gio|ngay\s+mai|toi\s+nay|trua\s+nay|luc\s+\d{1,2}(?::\d{2})?)\b"
)
_EXPLICIT_PUBLISH_START = re.compile(rf"^(?:please\s+)?{_PUBLISH}\b")
_PUBLISH_WITH_TARGET = re.compile(rf"\b{_PUBLISH}\b[^.;!?\n]*\b{_SOCIAL}\b")
_PUBLISH_PRONOUN = re.compile(r"\b(?:post|publish|upload|dang)\s+(?:it|no|anh|hinh|image|photo)\b")

_SOURCE_DELIVERY = re.compile(
    r"\b(?:gui|send|return|tra)\b[^.;!?\n]*"
    r"(?:\b(?:lai|back|day|here|chat\s+nay|this\s+chat|current\s+chat|cho\s+anh|cho\s+toi|to\s+me)\b|"
    r"\b(?:mot|1|one|exactly|dung)\b[^.;!?\n]*(?:anh|hinh|image|photo|picture)\b)"
)
_GENERIC_IMAGE_DELIVERY = re.compile(
    r"\b(?:gui|send|return|tra)\b[^.;!?\n]*\b(?:anh|hinh|image|photo|picture)\b"
)
_THIRD_PARTY_VI = re.compile(
    r"\bgui\s+(?:anh|hinh|image|photo|no|ket\s+qua)?\s*(?:cho|toi)\s+"
    r"(?!anh\b|toi\b|minh\b|day\b|chat\b)(?:[a-z0-9_]+)"
)
_THIRD_PARTY_EN = re.compile(
    r"\bsend\b[^.;!?\n]*\bto\s+(?!me\b|myself\b|here\b|this\b|the\s+current\b)[a-z0-9_]+"
)
_CHANNEL_SEND = re.compile(
    r"\b(?:gui|send|message|notify)\b[^.;!?\n]*\b(?:telegram|slack|teams|outlook|webhook|email)\b"
)
_EMAIL_ACTION = re.compile(r"\b(?:email|e-mail)\b")
_EXTERNAL_CALL = re.compile(
    r"\b(?:call|goi|notify|thong\s+bao|message)\b[^.;!?\n]*\b(?:webhook|telegram|slack|teams|email|outlook)\b"
)

_SPLIT = re.compile(
    r"[.!?;\n]+|\s+--\s+|,|\b(?:roi|sau\s+do|xong|afterwards|later|nhung|but|however)\b|"
    r"\bthen\b|\band\s+then\b|\b(?:and|va)\s+(?=(?:email|send|gui|post|publish|upload|dang|notify|message|call|goi)\b)"
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c)).replace("đ", "d")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def _positive_prefix(segment: str) -> str:
    tokens = segment.split()
    negated = [
        i
        for i, token in enumerate(tokens)
        if token in {"khong", "no", "dont", "don", "not", "never"}
    ]
    if negated:
        tokens = tokens[: min(negated)]
    return " ".join(tokens)


def _remove_benign_purpose(segment: str) -> tuple[str, bool, bool]:
    purpose = False
    timed = False
    cleaned = segment
    for pattern in (*_PURPOSE_PATTERNS, _OWNER_PUBLISH_PURPOSE, _NON_AGENT_PURPOSE):
        for match in tuple(pattern.finditer(cleaned)):
            purpose = True
            suffix = cleaned[match.end() :]
            if _TIMING.search(suffix):
                timed = True
                continue
            cleaned = cleaned[: match.start()] + " " + cleaned[match.end() :]
    return " ".join(cleaned.split()), purpose, timed


def _is_source_delivery(segment: str) -> bool:
    if _SOURCE_DELIVERY.search(segment):
        if _THIRD_PARTY_VI.search(segment) or _THIRD_PARTY_EN.search(segment):
            return False
        if _CHANNEL_SEND.search(segment) and not re.search(
            r"\b(?:day|here|chat\s+nay|this\s+chat|current\s+chat|cho\s+anh|cho\s+toi|to\s+me)\b",
            segment,
        ):
            return False
        return True
    if _GENERIC_IMAGE_DELIVERY.search(segment):
        return not (
            _THIRD_PARTY_VI.search(segment)
            or _THIRD_PARTY_EN.search(segment)
            or _CHANNEL_SEND.search(segment)
        )
    return False


def _external_effects(
    segment: str,
    *,
    original_segment: str,
    purpose_timed: bool,
    source_delivery: bool,
) -> tuple[VisualExternalEffect, ...]:
    effects: list[VisualExternalEffect] = []
    if (
        _AGENTIVE_PUBLISH.search(original_segment)
        or _THIRD_PARTY_PUBLISH.search(original_segment)
        or purpose_timed
    ):
        effects.append(VisualExternalEffect.PUBLISH)
    elif (
        _EXPLICIT_PUBLISH_START.search(segment)
        or _PUBLISH_WITH_TARGET.search(segment)
        or _PUBLISH_PRONOUN.search(segment)
    ):
        effects.append(VisualExternalEffect.PUBLISH)

    if _EMAIL_ACTION.search(segment):
        effects.append(VisualExternalEffect.THIRD_PARTY_SEND)
    elif not source_delivery and (
        _THIRD_PARTY_VI.search(segment)
        or _THIRD_PARTY_EN.search(segment)
        or _CHANNEL_SEND.search(segment)
    ):
        effects.append(VisualExternalEffect.THIRD_PARTY_SEND)

    if _EXTERNAL_CALL.search(segment) and not source_delivery:
        effects.append(VisualExternalEffect.EXTERNAL_CALL)
    return tuple(dict.fromkeys(effects))


def _residual_side_effect_text(request: str) -> str:
    without_copy = _QUOTED_COPY.sub(" ", request)
    normalized = _normalize(without_copy)
    residual: list[str] = []
    for raw_segment in _SPLIT.split(normalized):
        segment = _positive_prefix(raw_segment.strip())
        if not segment:
            continue
        cleaned, _, _ = _remove_benign_purpose(segment)
        if cleaned and not _is_source_delivery(cleaned):
            residual.append(cleaned)
    return " ".join(residual)


def build_visual_intent_contract(request: str) -> VisualIntentContract:
    """Interpret visual purpose, result delivery, and actual external effects.

    The output is deterministic and policy-neutral. Source-chat result delivery
    is distinct from publishing or communicating with another party.
    """

    normalized = _normalize(request)
    purpose: list[VisualPurpose] = []
    effects: list[VisualExternalEffect] = []
    delivery = VisualDelivery.NONE
    purpose_seen = False

    for raw_segment in _SPLIT.split(normalized):
        segment = _positive_prefix(raw_segment.strip())
        if not segment:
            continue

        cleaned, has_purpose, purpose_timed = _remove_benign_purpose(segment)
        if has_purpose:
            purpose.append(VisualPurpose.SOCIAL_CONTENT)
            purpose_seen = True

        if purpose_seen and _IMMEDIATE_COMMAND.search(segment):
            effects.append(VisualExternalEffect.PUBLISH)

        source_delivery = _is_source_delivery(cleaned)
        if source_delivery:
            delivery = VisualDelivery.SOURCE_CHANNEL

        effects.extend(
            _external_effects(
                cleaned,
                original_segment=segment,
                purpose_timed=purpose_timed,
                source_delivery=source_delivery,
            )
        )

    return VisualIntentContract(
        purpose=tuple(dict.fromkeys(purpose)),
        delivery=delivery,
        external_effects=tuple(dict.fromkeys(effects)),
        side_effect_text=_residual_side_effect_text(request),
    )
