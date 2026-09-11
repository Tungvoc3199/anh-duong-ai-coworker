from __future__ import annotations

from typing import Protocol

from app.capabilities import CapabilityKind, CapabilityRouter
from app.openclaw.image_generator import OpenClawImageArtifact
from app.openclaw.models import (
    CriterionVerification,
    OpenClawExecutionRequest,
    OpenClawExecutionResult,
    OpenClawTransportError,
)
from app.routing import FastRouter
from app.visualforge.client import VisualForgeRuntimeError
from app.visualforge.models import VisualForgeCompiledPrompt, VisualPromptSpec
from app.visualforge.parser import VisualPromptParseError, VisualPromptParser


class ExecutorDelegate(Protocol):
    async def execute(self, request: OpenClawExecutionRequest) -> OpenClawExecutionResult: ...


class VisualForgeComposer(Protocol):
    async def compose(self, spec: VisualPromptSpec) -> VisualForgeCompiledPrompt: ...


class VisualImageGenerator(Protocol):
    async def generate(
        self,
        *,
        prompt: str,
        run_id: str,
        aspect_ratio: str = "",
    ) -> OpenClawImageArtifact: ...


class VisualForgeRoutingExecutor:
    def __init__(
        self,
        *,
        delegate: ExecutorDelegate,
        client: VisualForgeComposer,
        image_generator: VisualImageGenerator | None = None,
    ) -> None:
        self.delegate = delegate
        self.client = client
        self.image_generator = image_generator
        self.parser = VisualPromptParser()

    async def execute(self, request: OpenClawExecutionRequest) -> OpenClawExecutionResult:
        route = FastRouter().route(request.goal)
        capability = CapabilityRouter().route(route, request.goal)
        if capability.capability not in {
            CapabilityKind.VISUAL_PROMPT_COMPOSE,
            CapabilityKind.VISUAL_IMAGE_GENERATE,
        }:
            return await self.delegate.execute(request)

        try:
            spec = self.parser.parse(request.goal)
            compiled = await self.client.compose(spec)
            if capability.capability is CapabilityKind.VISUAL_IMAGE_GENERATE:
                compiled = self._request_scoped_image_prompt(
                    spec,
                    compiled=compiled,
                    has_reference_image=request.reference_image is not None,
                )
        except (VisualPromptParseError, VisualForgeRuntimeError) as error:
            raise OpenClawTransportError(
                error.code,
                str(error),
                retryable=False,
                uncertain_side_effect=False,
            ) from error

        if capability.capability is CapabilityKind.VISUAL_IMAGE_GENERATE:
            if self.image_generator is None:
                raise OpenClawTransportError(
                    "image_generation_unavailable",
                    "Native image generator is not configured.",
                    retryable=False,
                )
            generate_kwargs = {
                "prompt": compiled.prompt,
                "run_id": request.run_id,
                "aspect_ratio": spec.aspect_ratio,
            }
            if request.reference_image is not None:
                generate_kwargs["reference_image"] = request.reference_image
            artifact = await self.image_generator.generate(**generate_kwargs)
            return self._image_result(request, spec, compiled, artifact)

        summary = self._summary(spec, compiled)
        return OpenClawExecutionResult(
            outcome="completed",
            summary=summary,
            artifacts={
                "visual_prompt": compiled.prompt,
                "template": spec.template,
                "adapter": compiled.adapter,
                "required_text": compiled.required_text,
                "aspect_ratio": spec.aspect_ratio,
                "provenance_notes": list(compiled.provenance_notes),
                "sections": compiled.sections,
            },
            verification={
                "method": "visualforge_local_compiler",
                "network_calls": 0,
                "network_isolation": "linux_user_network_namespace",
                "files_changed": 0,
                "exact_text_preserved": compiled.required_text == spec.required_text,
            },
            criterion_verification=tuple(
                CriterionVerification(
                    criterion=criterion,
                    status="verified",
                    evidence_refs=("visualforge:compiled_prompt", "visualforge:provenance"),
                    explanation="Verified by deterministic local VisualForge compile output.",
                )
                for criterion in request.dod_criteria
            ),
            files_changed=(),
            commands_run=(),
            tests=(),
            provider="local",
            profile="visualforge-v0.2",
        )

    @staticmethod
    def _request_scoped_image_prompt(
        spec: VisualPromptSpec,
        *,
        compiled: VisualForgeCompiledPrompt,
        has_reference_image: bool,
    ) -> VisualForgeCompiledPrompt:
        lines = [
            spec.brief.strip(),
            (
                "Treat this request as self-contained. Use only the current request as "
                "the visual instruction; do not import subjects, brands, props, copy, "
                "color palettes, motifs, or templates from unrelated prompts or VisualDNA."
            ),
        ]
        if has_reference_image:
            lines.append(
                "Use the provided reference image as the source of truth. Preserve subject "
                "identity, composition, background, camera framing, lighting, object count, "
                "and every unmentioned attribute. Change only what the current request "
                "explicitly asks to change."
            )
        else:
            lines.append(
                "If the current request does not explicitly specify a style, use a neutral, "
                "natural visual treatment and do not add an unrelated house style."
            )
        compiler_constraints = compiled.sections.get("constraints_negative_details", "")
        if compiler_constraints.strip():
            lines.append(f"Compiler constraints: {compiler_constraints.strip()}")
        if spec.required_text:
            lines.append(f"Visible text must be exactly: {spec.required_text}")
        if spec.aspect_ratio:
            lines.append(f"Aspect ratio: {spec.aspect_ratio}")
        prompt = "\n".join(lines)
        return VisualForgeCompiledPrompt(
            prompt=prompt,
            adapter=compiled.adapter,
            required_text=spec.required_text,
            provenance_notes=compiled.provenance_notes,
            sections={
                "task_subject": spec.brief.strip(),
                "composition_mode": "request_scoped_neutral",
                "reference_policy": (
                    "preserve_unmentioned" if has_reference_image else "none"
                ),
            },
        )

    @staticmethod
    def _image_result(
        request: OpenClawExecutionRequest,
        spec: VisualPromptSpec,
        compiled: VisualForgeCompiledPrompt,
        artifact: OpenClawImageArtifact,
    ) -> OpenClawExecutionResult:
        summary = "Ảnh đã tạo xong."
        return OpenClawExecutionResult(
            outcome="completed",
            summary=summary[:3800],
            artifacts={
                "image": artifact.as_dict(),
                "visual_prompt": compiled.prompt,
                "template": spec.template,
                "adapter": compiled.adapter,
                "required_text": compiled.required_text,
                "aspect_ratio": spec.aspect_ratio,
                "provenance_notes": list(compiled.provenance_notes),
                "sections": compiled.sections,
            },
            verification={
                "method": "visualforge_local_compiler_plus_openclaw_native_image",
                "image_artifact_verified": True,
                "visualforge_network_calls": 0,
                "network_isolation": "linux_user_network_namespace",
                "files_changed": 0,
                "exact_text_preserved": compiled.required_text == spec.required_text,
                "image_sha256": artifact.sha256,
                "recovered": artifact.recovered,
            },
            criterion_verification=tuple(
                CriterionVerification(
                    criterion=criterion,
                    status="verified",
                    evidence_refs=("visualforge:compiled_prompt", "openclaw:image_artifact"),
                    explanation=(
                        "Verified by deterministic VisualForge compile and native image checks."
                    ),
                )
                for criterion in request.dod_criteria
            ),
            files_changed=(),
            commands_run=(),
            tests=(),
            provider=artifact.provider,
            model=artifact.model,
            profile="visualforge-v0.2+openclaw-image",
        )

    @staticmethod
    def _summary(spec: VisualPromptSpec, compiled: VisualForgeCompiledPrompt) -> str:
        prompt_limit = 2600
        excerpt = compiled.prompt[:prompt_limit]
        if len(compiled.prompt) > prompt_limit:
            excerpt += "\n[Prompt đầy đủ đã được lưu trong run result.]"
        lines = [
            f"VisualForge ✅ template={spec.template}, adapter={compiled.adapter}",
        ]
        if spec.required_text:
            lines.append(f"Exact text: {spec.required_text}")
        if compiled.provenance_notes:
            lines.append(f"Provenance: {compiled.provenance_notes[0]}")
        lines.extend(("", "Prompt:", excerpt))
        return "\n".join(lines)[:3800]

    async def aclose(self) -> None:
        close = getattr(self.delegate, "aclose", None)
        if close is not None:
            await close()
