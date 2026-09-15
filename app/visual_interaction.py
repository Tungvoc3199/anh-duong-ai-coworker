from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class VisualOperation(StrEnum):
    CONVERSE = "converse"
    ANALYZE = "analyze"
    EXTRACT = "extract"
    VERIFY = "verify"
    COMPARE = "compare"
    SEARCH = "search"
    DERIVE_CONTENT = "derive_content"
    GENERATE = "generate"
    EDIT = "edit"
    TRANSFORM = "transform"
    ANNOTATE = "annotate"
    FILE_ACTION = "file_action"
    EXTERNAL_ACTION = "external_action"


class VisualImageRole(StrEnum):
    EVIDENCE = "evidence"
    EDIT_TARGET = "edit_target"
    SUBJECT_REFERENCE = "subject_reference"
    STYLE_REFERENCE = "style_reference"
    COMPOSITION_REFERENCE = "composition_reference"
    DATA_SOURCE = "data_source"


class VisualImageSource(StrEnum):
    CURRENT_UPLOAD = "current_upload"
    REPLIED_IMAGE = "replied_image"
    RECENT_ARTIFACT = "recent_artifact"
    EXPLICIT_REFERENCE = "explicit_reference"
    NONE = "none"
    AMBIGUOUS = "ambiguous"


class VisualOutput(StrEnum):
    TEXT = "text"
    STRUCTURED_DATA = "structured_data"
    IMAGE = "image"
    FILE = "file"
    EXTERNAL_EFFECT = "external_effect"


class VisualConstraint(StrEnum):
    NO_GENERATE = "no_generate"
    NO_EDIT = "no_edit"
    PRESERVE_IDENTITY = "preserve_identity"
    PRESERVE_BACKGROUND = "preserve_background"
    PRESERVE_TEXT = "preserve_text"


class VisualSideEffect(StrEnum):
    NONE = "none"
    SAVE = "save"
    OVERWRITE = "overwrite"
    DELETE = "delete"
    SEND = "send"
    PUBLISH = "publish"


class VisualInteractionContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_instruction: str
    operation: VisualOperation
    image_role: VisualImageRole | None
    image_source: VisualImageSource
    output: VisualOutput
    constraints: tuple[VisualConstraint, ...] = ()
    side_effect: VisualSideEffect = VisualSideEffect.NONE
    reference_image: str | None = None
    clarification_required: bool = False

    @model_validator(mode="after")
    def validate_reference_pairing(self) -> VisualInteractionContract:
        concrete = {
            VisualImageSource.CURRENT_UPLOAD,
            VisualImageSource.REPLIED_IMAGE,
            VisualImageSource.RECENT_ARTIFACT,
            VisualImageSource.EXPLICIT_REFERENCE,
        }
        if self.image_source in concrete:
            if not self.reference_image or not self.reference_image.startswith("media://"):
                raise ValueError("concrete image source requires a managed-media reference")
        elif self.reference_image is not None:
            raise ValueError("none or ambiguous image source cannot carry a reference")
        return self


_VISUAL_NOUNS = (
    "ảnh", "hình", "photo", "image", "poster", "visual", "logo", "screenshot",
)
_VISUAL_EDIT_TARGETS = (
    "váy", "vay", "áo", "ao", "cô gái", "co gai", "người mẫu", "nguoi mau",
    "khuôn mặt", "khuon mat", "tóc", "toc", "nền", "nen", "background",
    "foreground", "màu áo", "mau ao", "màu váy", "mau vay",
)

_VISUAL_PROMPT_PATTERNS = (
    re.compile(
        r"\b(?:prompt ảnh|prompt hình ảnh|prompt anh|prompt hinh anh|"
        r"visual prompt|image prompt)\b",
        re.IGNORECASE,
    ),
)

_PURPOSE_SOCIAL_PATTERNS = (
    re.compile(
        r"\b(?:để|de)\s+"
        r"(?:(?:anh|tôi|toi|mình|minh|khách hàng|khach hang)\s+(?:tự|tu\s+)?)?"
        r"(?:đăng|dang|post|publish|upload)\s+(?:lên|len\s+)?"
        r"(?:facebook|fb|instagram|tiktok|social media)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bto\s+(?:post|publish|upload)\s+"
        r"(?:(?:on|to)\s+)?(?:facebook|instagram|tiktok|social media)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfor\s+(?:(?:my|a|an|the)\s+)?"
        r"(?:facebook|instagram|tiktok|social media)\s+(?:post|content)\b",
        re.IGNORECASE,
    ),
)



_EXTERNAL_TIMING = re.compile(
    r"\b(?:bây giờ|bay gio|ngay mai|tối nay|toi nay|"
    r"lúc\s+\d{1,2}(?::\d{2})?|now|right now|asap|tomorrow|tonight|"
    r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
    re.IGNORECASE,
)

_EXPLICIT_EXTERNAL_PATTERNS = (
    re.compile(
        r"\b(?:rồi|roi|xong|sau đó|sau do|then|and then)\s+"
        r"(?:đăng|dang|post|publish|upload|gửi|gui|send|email)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^(?:đăng|dang|post|publish|upload|gửi|gui|send|email)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:cho em|nho em|nhờ em|bao em|bảo em|muon em|muốn em|"
        r"want you to|need you to|ask you to)\s+"
        r"(?:đăng|dang|post|publish|upload|gửi|gui|send|email)\b",
        re.IGNORECASE,
    ),

    re.compile(
        r"\b(?:gửi|gui|send)\b[^.;!?\n]*\b(?:cho|to)\s+"
        r"(?!anh\b|toi\b|tôi\b|minh\b|mình\b|me\b|here\b|đây\b|day\b)[\w-]+",
        re.IGNORECASE,
    ),
)


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _contains_literal_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE)
        for phrase in phrases
    )


def _contains_visual_noun(text: str) -> bool:
    cleaned = re.sub(r"(?<!\w)(?:ảnh|anh)\s+hưởng(?!\w)", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"(?<!\w)(?:cấu hình|cau hinh|mô hình|mo hinh|hình thức|hinh thuc|"
        r"docker image|container image|disk image)(?!\w)",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    return _contains_literal_phrase(cleaned, _VISUAL_NOUNS)


def _is_visual_prompt_compose(text: str) -> bool:
    return any(pattern.search(text) for pattern in _VISUAL_PROMPT_PATTERNS)


def _has_explicit_external_action(text: str) -> bool:
    if any(pattern.search(text) for pattern in _EXPLICIT_EXTERNAL_PATTERNS):
        return True
    purpose_matches = [
        match
        for pattern in _PURPOSE_SOCIAL_PATTERNS
        for match in pattern.finditer(text)
    ]
    for match in purpose_matches:
        suffix = text[match.end():]
        if _EXTERNAL_TIMING.search(suffix):
            return True
    without_purpose = text
    for pattern in _PURPOSE_SOCIAL_PATTERNS:
        without_purpose = pattern.sub(" ", without_purpose)
    return bool(
        re.search(
            r"\b(?:đăng|dang|post|publish|upload)\b[^.;!?\n]*"
            r"\b(?:facebook|fb|instagram|tiktok|social media)\b",
            without_purpose,
            re.IGNORECASE,
        )
    )


def _mask_negated_actions(
    text: str,
) -> tuple[str, tuple[VisualConstraint, ...]]:
    constraints: list[VisualConstraint] = []
    masked = text
    negations = (
        (
            VisualConstraint.NO_GENERATE,
            r"\b(?:(?:không|k|đừng|dont|don't|do not)\s+"
            r"(?:tạo|tao|generate|create|make)(?:\s+lại)?|"
            r"(?:không|k)\s+bảo(?:\s+\w+){0,2}\s+"
            r"(?:tạo|tao|generate|create|make)(?:\s+lại)?)\b",
        ),
        (
            VisualConstraint.NO_EDIT,
            r"\b(?:không|k|đừng|dont|don't|do not)\s+"
            r"(?:sửa|sua|edit|chỉnh|chinh|đổi|doi|thay)\b",
        ),
    )
    for constraint, pattern in negations:
        if re.search(pattern, masked, flags=re.IGNORECASE):
            constraints.append(constraint)
            masked = re.sub(pattern, " ", masked, flags=re.IGNORECASE)
    return masked, tuple(dict.fromkeys(constraints))


def _visual_operation(
    text: str,
    source: VisualImageSource,
) -> VisualOperation | None:
    has_visual_noun = _contains_visual_noun(text)
    has_visual_evidence = source is not VisualImageSource.NONE
    has_visual_edit_target = _contains_literal_phrase(text, _VISUAL_EDIT_TARGETS)
    has_visual_context = has_visual_noun or has_visual_evidence or has_visual_edit_target

    if _has_explicit_external_action(text) and (
        has_visual_noun or has_visual_evidence
    ):
        return VisualOperation.EXTERNAL_ACTION
    if _contains_any(
        text,
        ("lưu file", "save file", "ghi file", "xuất file", "export file"),
    ):
        if has_visual_noun or has_visual_evidence:
            return VisualOperation.FILE_ACTION
    if has_visual_context and _contains_any(
        text,
        ("khoanh", "đánh dấu", "annotate", "circle", "mark"),
    ):
        return VisualOperation.ANNOTATE
    if has_visual_context and _contains_any(
        text,
        (
            "biến thành",
            "chuyển thành",
            "transform",
            "convert",
            "đổi phong cách",
            "style transfer",
        ),
    ):
        return VisualOperation.TRANSFORM
    if has_visual_context and _contains_any(
        text,
        (
            "sửa", "sua", "chỉnh", "chinh", "đổi", "doi", "thay",
            "xóa", "xoa", "thêm", "them", "edit", "replace", "remove",
        ),
    ):
        return VisualOperation.EDIT
    if has_visual_context and _contains_any(
        text,
        (
            "dựng lại", "dung lai", "làm lại", "lam lai",
            "tạo lại", "tao lai", "vẽ lại", "ve lai",
            "recreate", "remake", "redraw", "rebuild",
        ),
    ):
        return VisualOperation.GENERATE
    if _contains_any(text, ("tạo", "tao", "generate", "create", "make")) and (
        has_visual_noun
        or _contains_any(text, ("một cô gái", "mot co gai", "một người", "mot nguoi"))
    ):
        return VisualOperation.GENERATE
    if (has_visual_noun or has_visual_evidence) and _contains_any(
        text,
        ("trích xuất", "trich xuat", "ocr", "đọc chữ", "doc chu", "extract text"),
    ):
        return VisualOperation.EXTRACT
    if (has_visual_noun or has_visual_evidence) and _contains_any(
        text,
        ("so sánh", "so sanh", "compare"),
    ):
        return VisualOperation.COMPARE
    if (has_visual_noun or has_visual_evidence) and _contains_any(
        text,
        ("xác minh", "xac minh", "verify"),
    ):
        return VisualOperation.VERIFY
    if (has_visual_noun or has_visual_evidence) and _contains_any(
        text,
        (
            "phân tích", "phan tich", "nhận xét", "nhan xet", "sai cái gì",
            "sai gi", "sai gì", "xem những điều", "xem nhung dieu",
        ),
    ):
        return VisualOperation.ANALYZE
    if has_visual_noun and _contains_any(
        text,
        ("có thấy", "co thay", "xem", "đúng k", "dung k", "đúng không"),
    ):
        return VisualOperation.ANALYZE
    if _contains_any(text, ("tìm ảnh", "tim anh", "search image", "search photo")):
        return VisualOperation.SEARCH
    if _contains_any(
        text,
        ("viết caption", "viet caption", "viết nội dung", "viet noi dung", "derive content"),
    ) and (has_visual_noun or has_visual_evidence):
        return VisualOperation.DERIVE_CONTENT
    if has_visual_noun or has_visual_evidence:
        return VisualOperation.CONVERSE
    return None


def _role_for(
    operation: VisualOperation,
    text: str,
    source: VisualImageSource,
) -> VisualImageRole | None:
    if source in {VisualImageSource.NONE, VisualImageSource.AMBIGUOUS}:
        return None
    if operation in {
        VisualOperation.ANALYZE,
        VisualOperation.VERIFY,
        VisualOperation.COMPARE,
        VisualOperation.CONVERSE,
    }:
        return VisualImageRole.EVIDENCE
    if operation is VisualOperation.EXTRACT:
        return VisualImageRole.DATA_SOURCE
    if operation in {VisualOperation.EDIT, VisualOperation.TRANSFORM, VisualOperation.ANNOTATE}:
        return VisualImageRole.EDIT_TARGET
    if operation is VisualOperation.GENERATE:
        if _contains_any(text, ("phong cách", "phong cach", "style")):
            return VisualImageRole.STYLE_REFERENCE
        if _contains_any(text, ("bố cục", "bo cuc", "composition", "layout")):
            return VisualImageRole.COMPOSITION_REFERENCE
        if _contains_any(text, ("nhân vật", "nhan vat", "người này", "nguoi nay", "subject")):
            return VisualImageRole.SUBJECT_REFERENCE
    return None


def _output_for(operation: VisualOperation) -> VisualOutput:
    if operation is VisualOperation.EXTRACT:
        return VisualOutput.STRUCTURED_DATA
    if operation in {
        VisualOperation.GENERATE,
        VisualOperation.EDIT,
        VisualOperation.TRANSFORM,
        VisualOperation.ANNOTATE,
    }:
        return VisualOutput.IMAGE
    if operation is VisualOperation.FILE_ACTION:
        return VisualOutput.FILE
    if operation is VisualOperation.EXTERNAL_ACTION:
        return VisualOutput.EXTERNAL_EFFECT
    return VisualOutput.TEXT


def _side_effect_for(operation: VisualOperation, text: str) -> VisualSideEffect:
    if operation is VisualOperation.FILE_ACTION:
        if _contains_any(text, ("xóa", "xoa", "delete")):
            return VisualSideEffect.DELETE
        if _contains_any(text, ("ghi đè", "ghi de", "overwrite")):
            return VisualSideEffect.OVERWRITE
        return VisualSideEffect.SAVE
    if operation is VisualOperation.EXTERNAL_ACTION:
        if _contains_any(text, ("đăng", "dang", "post", "publish")):
            return VisualSideEffect.PUBLISH
        return VisualSideEffect.SEND
    return VisualSideEffect.NONE


def _needs_target(operation: VisualOperation) -> bool:
    return operation in {
        VisualOperation.ANALYZE,
        VisualOperation.EXTRACT,
        VisualOperation.VERIFY,
        VisualOperation.COMPARE,
        VisualOperation.EDIT,
        VisualOperation.TRANSFORM,
        VisualOperation.ANNOTATE,
    }


def should_bind_recent_visual_candidate(raw_instruction: str) -> bool:
    lowered = raw_instruction.casefold()
    base = build_visual_interaction_contract(lowered)
    if base is not None and base.clarification_required:
        return True
    visual_noun = _contains_visual_noun(lowered)
    return visual_noun and _contains_any(
        lowered,
        (
            "dựng lại", "dung lai", "làm lại", "lam lai",
            "tạo lại", "tao lai", "vẽ lại", "ve lai",
            "recreate", "remake", "redraw", "rebuild",
        ),
    )


def build_visual_interaction_contract(
    raw_instruction: str,
    *,
    image_source: VisualImageSource = VisualImageSource.NONE,
    reference_image: str | None = None,
) -> VisualInteractionContract | None:
    lowered = raw_instruction.casefold()
    if _is_visual_prompt_compose(lowered):
        return None
    effective, constraints = _mask_negated_actions(lowered)
    operation = _visual_operation(effective, image_source)
    if operation is None:
        return None

    source = image_source
    if (
        source in {VisualImageSource.NONE, VisualImageSource.AMBIGUOUS}
        and reference_image is not None
    ):
        raise ValueError("none or ambiguous image source cannot carry a reference")
    concrete_sources = {
        VisualImageSource.CURRENT_UPLOAD,
        VisualImageSource.REPLIED_IMAGE,
        VisualImageSource.RECENT_ARTIFACT,
        VisualImageSource.EXPLICIT_REFERENCE,
    }
    if source in concrete_sources and reference_image is None:
        raise ValueError("concrete image source requires a managed-media reference")

    clarification_required = _needs_target(operation) and source in {
        VisualImageSource.NONE,
        VisualImageSource.AMBIGUOUS,
    }
    role = _role_for(operation, lowered, source)
    return VisualInteractionContract(
        raw_instruction=raw_instruction,
        operation=operation,
        image_role=role,
        image_source=source,
        output=_output_for(operation),
        constraints=constraints,
        side_effect=_side_effect_for(operation, lowered),
        reference_image=reference_image,
        clarification_required=clarification_required,
    )
