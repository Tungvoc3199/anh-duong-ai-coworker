from __future__ import annotations

from dataclasses import dataclass

from app.semantic_intent import VisualCompilerType
from app.visualforge.models import VisualForgeCompiledPrompt, VisualPromptSpec

_PREFIX = "visual_compiler:"


@dataclass(frozen=True)
class VisualCompilerContract:
    compiler_type: VisualCompilerType
    identity_lock: bool = False
    preserve_unmentioned: bool = False

    @classmethod
    def from_constraints(cls, constraints: tuple[str, ...]) -> VisualCompilerContract | None:
        values: dict[str, str] = {}
        for item in constraints:
            if not item.startswith(_PREFIX):
                continue
            key, sep, value = item[len(_PREFIX):].partition("=")
            if sep:
                values[key.strip()] = value.strip()
        raw_type = values.get("type")
        if raw_type is None:
            return None
        return cls(
            compiler_type=VisualCompilerType(raw_type),
            identity_lock=values.get("identity_lock") == "true",
            preserve_unmentioned=values.get("preserve_unmentioned") == "true",
        )


def compile_visual_prompt(
    spec: VisualPromptSpec,
    *,
    contract: VisualCompilerContract,
    has_reference_image: bool,
) -> VisualForgeCompiledPrompt:
    lines = [
        spec.brief.strip(),
        (
            "Treat this request as self-contained. Use only the current request and the "
            "provided reference image, if any. Do not import subjects, brands, props, "
            "copy, palettes, motifs, templates, style, or VisualDNA from unrelated turns."
        ),
    ]

    kind = contract.compiler_type
    if kind is VisualCompilerType.PORTRAIT_PERSONA:
        lines.append(
            "Portrait/persona compiler: keep the person as the semantic focal subject. "
            "Use coherent anatomy, wardrobe, accessories, hair, makeup, setting, camera, "
            "and lighting only as required by the current request."
        )
        if contract.identity_lock:
            lines.append(
                "Identity lock: preserve the established subject identity and stable facial "
                "features; do not substitute a different person."
            )
    elif kind is VisualCompilerType.PRODUCT:
        lines.append(
            "Product compiler: keep the requested product as the semantic focal object. "
            "Preserve requested product geometry, packaging hierarchy, logos, labels, "
            "materials, and object count; do not import persona styling."
        )
    elif kind is VisualCompilerType.POSTER_TEXT:
        lines.append(
            "Poster/text compiler: honor the requested layout hierarchy, composition, "
            "safe areas, and copy placement. Do not invent extra copy."
        )
    elif kind is VisualCompilerType.REFERENCE_EDIT:
        if not has_reference_image:
            raise ValueError("reference_edit compiler requires a reference image")
        lines.append(
            "Reference/edit compiler: use the provided reference image as the source of "
            "truth for the requested edit."
        )
        if contract.preserve_unmentioned:
            lines.append(
                "Preserve composition, background, camera framing, lighting, object count, "
                "and every unmentioned attribute. Change only what the current request "
                "explicitly asks to change."
            )
        if contract.identity_lock:
            lines.append(
                "Preserve subject identity and stable facial features from the reference."
            )

    if has_reference_image and kind is not VisualCompilerType.REFERENCE_EDIT:
        lines.append(
            "Use the provided reference image only as authorized visual evidence for this "
            "request; do not import unrelated style or prompt history."
        )
    if contract.preserve_unmentioned and kind is not VisualCompilerType.REFERENCE_EDIT:
        lines.append("Preserve every unmentioned attribute from the authorized reference.")
    if spec.required_text:
        lines.append(f"Visible text must be exactly: {spec.required_text}")
    if spec.aspect_ratio:
        lines.append(f"Aspect ratio: {spec.aspect_ratio}")

    return VisualForgeCompiledPrompt(
        prompt="\n".join(lines),
        adapter="gpt-image",
        required_text=spec.required_text,
        provenance_notes=(),
        sections={
            "task_subject": spec.brief.strip(),
            "compiler_type": kind.value,
            "composition_mode": "semantic_request_local",
            "reference_policy": (
                "preserve_unmentioned"
                if kind is VisualCompilerType.REFERENCE_EDIT or contract.preserve_unmentioned
                else "authorized_reference_only" if has_reference_image else "none"
            ),
            "identity_lock": "true" if contract.identity_lock else "false",
        },
    )
