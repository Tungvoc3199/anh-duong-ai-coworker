from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from app.async_tasks import AsyncRunStatus, AsyncTaskMode, AsyncTaskRun, NotificationStatus
from app.openclaw import OpenClawNotifier
from app.openclaw.image_generator import OpenClawImageArtifact
from app.openclaw.models import OpenClawExecutionRequest
from app.visualforge import VisualForgeCompiledPrompt, VisualForgeRoutingExecutor


class PoisonVisualDNAComposer:
    """Models the stale top-1 product DNA proven in production evidence."""

    def __init__(self) -> None:
        self.specs: list[Any] = []

    async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
        self.specs.append(spec)
        return VisualForgeCompiledPrompt(
            prompt=(
                "Use VisualDNA 'FMCG 棒棒糖霓虹广告'. Chupa Chups India. "
                "giant lollipop, candy shards, neon Mumbai, billboard"
            ),
            adapter="gpt-image",
            provenance_notes=("freestylefly-fmcg-9f03e278",),
            sections={"composition": "giant lollipop, candy shards"},
        )


class CaptureImageGenerator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        prompt: str,
        run_id: str,
        aspect_ratio: str = "",
        reference_image: str | None = None,
    ) -> OpenClawImageArtifact:
        self.calls.append(
            {
                "prompt": prompt,
                "run_id": run_id,
                "aspect_ratio": aspect_ratio,
                "reference_image": reference_image,
            }
        )
        return OpenClawImageArtifact(
            path=Path("/tmp") / f"{run_id}.png",
            media_path=f"/home/node/.openclaw/media/anh-duong/{run_id}.png",
            sha256="a" * 64,
            mime_type="image/png",
            size_bytes=123,
            width=1024,
            height=1536,
            provider="openai",
            model="cx/gpt-5.5-image",
            requested_aspect_ratio=aspect_ratio,
            rendered_size="1024x1536",
            recovered=False,
        )


def _image_request(goal: str, *, reference_image: str | None = None) -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_de",
        run_id="run_de",
        attempt=1,
        idempotency_key="run_de:1",
        project_id="proj_de",
        goal=goal,
        mode="quick",
        workspace="/tmp",
        reference_image=reference_image,
        dod_criteria=("deliver one generated image",),
    )


@pytest.mark.asyncio
async def test_clean_text_to_image_prompt_does_not_import_unrequested_visual_dna() -> None:
    composer = PoisonVisualDNAComposer()
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=composer,
        image_generator=generator,
    )
    goal = "Tạo cho anh một ảnh cô gái Việt Nam 20 tuổi mặc áo dài trắng đứng bên hồ sen"

    result = await executor.execute(_image_request(goal))

    assert len(generator.calls) == 1
    prompt = cast(str, generator.calls[0]["prompt"])
    assert goal in prompt
    for stale in ("chupa", "lollipop", "candy", "billboard", "fmcg", "mumbai"):
        assert stale not in prompt.casefold()
    assert result.artifacts["visual_prompt"] == prompt
    assert result.artifacts["template"] == "request-scoped-image"
    assert result.artifacts["provenance_notes"] == []


@pytest.mark.asyncio
async def test_clean_image_revision_preserves_reference_without_unrelated_visual_dna() -> None:
    composer = PoisonVisualDNAComposer()
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=composer,
        image_generator=generator,
    )
    reference = "media://inbound/11111111-1111-4111-8111-111111111111.jpg"
    goal = "Tạo ảnh chỉnh sửa từ ảnh tham chiếu. Yêu cầu hiện tại: Đổi váy sang màu vàng"

    result = await executor.execute(_image_request(goal, reference_image=reference))

    assert len(generator.calls) == 1
    call = generator.calls[0]
    assert call["reference_image"] == reference
    prompt = cast(str, call["prompt"])
    assert "Đổi váy sang màu vàng" in prompt
    assert "preserve" in prompt.casefold() or "giữ nguyên" in prompt.casefold()
    for stale in ("chupa", "lollipop", "candy", "billboard", "fmcg", "mumbai"):
        assert stale not in prompt.casefold()
    assert result.artifacts["template"] == "request-scoped-reference-revision"
    assert result.artifacts["provenance_notes"] == []


def _notification_run(
    *,
    status: AsyncRunStatus,
    result: dict[str, Any],
    request: dict[str, Any],
) -> AsyncTaskRun:
    now = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
    return AsyncTaskRun(
        id="run_de_notify",
        task_id="task_de_notify",
        status=status,
        mode=AsyncTaskMode.BUILD,
        goal=cast(str, request.get("goal") or "Tạo ảnh"),
        workspace="/tmp",
        request_json=json.dumps(request, ensure_ascii=False),
        checkpoint_json=None,
        result_json=json.dumps(result, ensure_ascii=False),
        attempt=1,
        max_attempts=3,
        run_after=now,
        lease_owner=None,
        lease_expires_at=None,
        idempotency_key="telegram:de:1",
        external_run_id=None,
        last_error_code=cast(str | None, result.get("error_code")),
        last_error_message=cast(str | None, result.get("summary")),
        source_chat_id="7535966424",
        notification_status=NotificationStatus.PENDING,
        notification_attempts=0,
        created_at=now,
        updated_at=now,
        version=1,
    )


@pytest.mark.asyncio
async def test_image_success_outbound_caption_is_user_safe() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"messageId": "901"}})

    run = _notification_run(
        status=AsyncRunStatus.COMPLETED,
        request={"goal": "Tạo ảnh áo dài bên hồ sen"},
        result={
            "outcome": "completed",
            "summary": (
                "Ảnh đã tạo xong bằng VisualForge + cx/gpt-5.5-image. "
                "provider=openai tool=image_generate"
            ),
            "profile": "visualforge-v0.2+openclaw-image",
            "artifacts": {
                "image": {
                    "media_path": "/home/node/.openclaw/media/anh-duong/run_de_notify.png",
                    "mime_type": "image/png",
                }
            },
            "verification": {"image_artifact_verified": True},
        },
    )
    notifier = OpenClawNotifier(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(handler),
    )

    await notifier.send_final(run)

    message = cast(str, cast(dict[str, Any], captured["args"])["message"])
    assert "ảnh" in message.casefold()
    for internal in ("visualforge", "gpt-5.5", "provider=", "tool=", "image_generate", "openai"):
        assert internal not in message.casefold()


@pytest.mark.asyncio
async def test_image_failure_outbound_is_safe_without_magic_constraint_set() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"messageId": "902"}})

    run = _notification_run(
        status=AsyncRunStatus.BLOCKED,
        request={
            "goal": "Tạo ảnh chỉnh sửa từ ảnh tham chiếu. Yêu cầu hiện tại: Đổi váy sang màu vàng",
            "reference_image": "media://inbound/11111111-1111-4111-8111-111111111111.jpg",
            "constraints": [],
        },
        result={
            "outcome": "blocked",
            "summary": (
                "Definition of done is not fully verified by evidence. "
                "provider=openai model=cx/gpt-5.5-image"
            ),
            "error_code": "dod_evidence_missing",
            "artifacts": [],
            "verification": [],
        },
    )
    notifier = OpenClawNotifier(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(handler),
    )

    await notifier.send_final(run)

    message = cast(str, cast(dict[str, Any], captured["args"])["message"])
    assert "ảnh" in message.casefold()
    for internal in (
        "definition of done",
        "dod_evidence_missing",
        "provider=",
        "model=",
        "gpt-5.5",
        "openai",
    ):
        assert internal not in message.casefold()


@pytest.mark.asyncio
async def test_request_scoped_image_prompt_preserves_safe_compiler_constraints() -> None:
    class ConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Keep the primary subject inside the safe area. "
                            "Do not add extra logos or unsupported copy."
                        ),
                    }
                }
            )

    composer = ConstraintComposer()
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=composer,
        image_generator=generator,
    )

    await executor.execute(_image_request("Tạo ảnh sản phẩm tối giản"))

    prompt = cast(str, generator.calls[0]["prompt"])
    assert "safe area" in prompt.casefold()
    assert "extra logos" in prompt.casefold()
    for stale in ("chupa", "lollipop", "candy", "billboard", "fmcg", "mumbai"):
        assert stale not in prompt.casefold()


@pytest.mark.asyncio
async def test_completed_image_like_run_without_verified_media_never_claims_success() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"messageId": "903"}})

    run = _notification_run(
        status=AsyncRunStatus.COMPLETED,
        request={"goal": "Tạo ảnh áo dài bên hồ sen", "constraints": []},
        result={
            "outcome": "completed",
            "summary": (
                "VisualForge completed without verified media. "
                "provider=openai model=cx/gpt-5.5-image tool=image_generate"
            ),
            "artifacts": [],
            "verification": [],
        },
    )
    notifier = OpenClawNotifier(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(handler),
    )

    await notifier.send_final(run)

    message = cast(str, cast(dict[str, Any], captured["args"])["message"])
    assert message != "Ảnh đã tạo xong."
    assert "chưa" in message.casefold()
    for internal in (
        "visualforge",
        "verified media",
        "provider=",
        "model=",
        "tool=",
        "image_generate",
        "openai",
        "gpt-5.5",
    ):
        assert internal not in message.casefold()

@pytest.mark.asyncio
async def test_portrait_generation_drops_unrelated_product_only_compiler_constraints() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape, packaging hierarchy, logos, "
                            "and visible labels. "
                            "Do not invent certifications, awards, discounts, or claims. "
                            "Keep the product as the clearest focal point."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    goal = "Tạo ảnh cô gái Việt Nam 20 tuổi mặc áo dài trắng đứng bên hồ sen"

    await executor.execute(_image_request(goal))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    for unrelated in ("product shape", "packaging", "certifications", "discounts", "product as"):
        assert unrelated not in prompt


@pytest.mark.asyncio
async def test_fresh_person_generation_requests_coherent_accessories_and_footwear() -> None:
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=PoisonVisualDNAComposer(),
        image_generator=generator,
    )

    await executor.execute(
        _image_request("Tạo ảnh cô gái Việt Nam mặc áo dài trắng thanh lịch bên hồ sen")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "accessor" in prompt
    assert "footwear" in prompt or "shoes" in prompt
    assert "hair" in prompt
    assert "makeup" in prompt
    assert "occasion" in prompt
    assert "setting" in prompt


@pytest.mark.asyncio
async def test_real_product_generation_keeps_product_compiler_constraints() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape, packaging hierarchy, logos, "
                            "and visible labels. "
                            "Do not invent certifications, awards, discounts, or claims."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )

    await executor.execute(
        _image_request("Tạo ảnh quảng cáo chai nước hoa Chanel")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" in prompt
    assert "packaging" in prompt
    assert "visible labels" in prompt

@pytest.mark.asyncio
async def test_person_product_generation_with_explicit_product_focus_keeps_constraints() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape, packaging hierarchy, logos, "
                            "and visible labels. Do not invent certifications or claims."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )

    await executor.execute(
        _image_request("Tạo ảnh cô gái Việt Nam quảng cáo chai nước hoa Chanel")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" in prompt
    assert "packaging" in prompt
    assert "visible labels" in prompt


@pytest.mark.asyncio
async def test_portrait_mixed_constraints_keep_generic_clauses_only() -> None:
    class MixedConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy. "
                            "Keep the primary subject inside the safe area. "
                            "Do not add unsupported copy or extra logos."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=MixedConstraintComposer(),
        image_generator=generator,
    )

    await executor.execute(
        _image_request("Tạo ảnh cô gái Việt Nam mặc áo dài trắng bên hồ sen")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "packaging" not in prompt
    assert "safe area" in prompt
    assert "unsupported copy" in prompt
    assert "extra logos" in prompt


@pytest.mark.asyncio
async def test_person_holding_requested_product_keeps_product_fidelity_constraints() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape, packaging hierarchy, logos, "
                            "and visible labels."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Tạo ảnh cô gái cầm chai nước hoa Chanel"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" in prompt
    assert "packaging" in prompt
    assert "visible labels" in prompt


@pytest.mark.asyncio
async def test_portrait_mixed_single_clause_keeps_safe_area_without_product_bleed() -> None:
    class MixedConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and keep the primary subject "
                            "inside the safe area."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=MixedConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(
        _image_request("Tạo ảnh cô gái Việt Nam mặc áo dài trắng bên hồ sen")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "safe area" in prompt


@pytest.mark.asyncio
async def test_orange_clothing_does_not_masquerade_as_requested_object_focus() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(
        _image_request("Tạo ảnh cô gái Việt Nam mặc áo dài màu cam bên hồ sen")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "packaging" not in prompt


@pytest.mark.asyncio
async def test_unaccented_vietnamese_product_focus_keeps_product_constraints() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape, packaging hierarchy, logos, "
                            "and visible labels."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(
        _image_request("Tao anh co gai su dung chai nuoc hoa Chanel")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" in prompt
    assert "packaging" in prompt
    assert "visible labels" in prompt


@pytest.mark.asyncio
async def test_productive_portrait_does_not_trigger_product_focus_by_substring() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(
        _image_request("Tạo ảnh chân dung một productive woman tại bàn làm việc")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "packaging" not in prompt


@pytest.mark.asyncio
async def test_person_holding_natural_prop_does_not_keep_product_constraints() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape, packaging hierarchy, logos, "
                            "and visible labels."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Tạo ảnh cô gái cầm bó hoa sen bên hồ"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "packaging" not in prompt

@pytest.mark.asyncio
async def test_person_beside_requested_product_keeps_product_fidelity_constraints() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape, packaging hierarchy, logos, "
                            "and visible labels."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Tạo ảnh cô gái bên chai nước hoa Chanel"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" in prompt
    assert "packaging" in prompt
    assert "visible labels" in prompt

@pytest.mark.asyncio
async def test_portrait_drops_separate_product_label_and_claim_clauses() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Keep logos and visible labels exact. "
                            "Do not invent awards or claims. "
                            "Keep the primary subject inside the safe area."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Tạo ảnh cô gái Việt Nam mặc áo dài trắng bên hồ sen"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "visible labels" not in prompt
    assert "awards" not in prompt
    assert "claims" not in prompt
    assert "safe area" in prompt

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal",
    (
        "Tạo ảnh cô gái Việt Nam mặc giày cao gót bên hồ sen",
        "Tạo ảnh cô gái Việt Nam đeo túi thanh lịch bên hồ sen",
        "Tạo ảnh cô gái Việt Nam đeo đồng hồ thanh lịch bên hồ sen",
    ),
)
async def test_portrait_wardrobe_accessories_do_not_trigger_product_constraints(goal: str) -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy. "
                            "Keep logos and visible labels exact."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request(goal))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "packaging" not in prompt
    assert "visible labels" not in prompt

@pytest.mark.asyncio
async def test_portrait_camera_direction_does_not_trigger_product_constraints() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Tạo ảnh cô gái Việt Nam nhìn vào camera bên hồ sen"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "packaging" not in prompt

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal",
    (
        "Tạo ảnh cô gái mặc áo dài trắng phù hợp với bối cảnh hồ sen",
        "Tạo ảnh cô gái đang chải tóc bên hồ sen",
    ),
)
async def test_vietnamese_accent_collisions_do_not_trigger_product_constraints(goal: str) -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request(goal))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "packaging" not in prompt

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal",
    (
        "Tạo ảnh cô gái cầm lon Coca-Cola",
        "Create an image of a model holding a can of Coke",
    ),
)
async def test_common_packaged_product_forms_keep_product_fidelity_constraints(goal: str) -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape, packaging hierarchy, logos, "
                            "and visible labels."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request(goal))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" in prompt
    assert "packaging" in prompt
    assert "visible labels" in prompt


@pytest.mark.asyncio
async def test_portrait_drops_separate_product_brand_logo_fidelity_clause() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact brand logos. Preserve exact product shape."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Tạo ảnh cô gái mặc áo dài trắng bên hồ sen"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "brand logos" not in prompt
    assert "product shape" not in prompt


@pytest.mark.asyncio
async def test_portrait_preserves_generic_logo_watermark_text_artifact_ban() -> None:
    class GenericSafetyComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Do not add logos, watermarks, or text artifacts."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=GenericSafetyComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Tạo ảnh cô gái mặc áo dài trắng bên hồ sen"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "logos" in prompt
    assert "watermarks" in prompt
    assert "text artifacts" in prompt

@pytest.mark.asyncio
async def test_plain_person_prompt_does_not_inject_wardrobe_styling_guidance() -> None:
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=PoisonVisualDNAComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Tạo ảnh cô gái đứng bên hồ sen"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "coordinate footwear" not in prompt
    assert "accessories, hair, and makeup" not in prompt


@pytest.mark.asyncio
async def test_explicit_styled_clothing_keeps_wardrobe_coherence_guidance() -> None:
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=PoisonVisualDNAComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Tạo ảnh cô gái mặc áo dài trắng bên hồ sen"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "coordinate footwear" in prompt
    assert "accessories, hair, and makeup" in prompt

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal",
    (
        "Create an image of a model wearing a white dress",
        "Create an image of a person by a lotus lake",
        "Create an image of a man standing by a lotus lake",
        "Create an image of a boy standing by a lotus lake",
    ),
)
async def test_common_english_person_prompts_filter_stale_product_constraints(goal: str) -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy. "
                            "Keep visible labels exact."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request(goal))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "packaging" not in prompt
    assert "visible labels" not in prompt

@pytest.mark.asyncio
async def test_reference_revision_uses_reference_fidelity_without_stale_product_dna() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy. "
                            "Keep visible labels exact. "
                            "Keep the product as the clearest focal point. "
                            "Preserve promotional discounts and badge claims."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(
        _image_request(
            "Tạo ảnh chỉnh sửa từ ảnh tham chiếu. Yêu cầu hiện tại: Làm người mẫu mỉm cười",
            reference_image="media://inbound/11111111-1111-4111-8111-111111111111.jpg",
        )
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert (
        "when present in the reference, preserve product shape, packaging, "
        "logos, and visible labels"
        in prompt
    )
    assert "packaging hierarchy" not in prompt
    assert "clearest focal point" not in prompt
    assert "promotional discounts" not in prompt
    assert "badge claims" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal",
    (
        "Create an image of a model holding a Coke can",
        "Create an image of a woman holding a Coke can",
    ),
)
async def test_brand_before_packaged_form_keeps_product_fidelity_constraints(goal: str) -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy. "
                            "Keep visible labels exact."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request(goal))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" in prompt
    assert "packaging" in prompt
    assert "visible labels" in prompt

@pytest.mark.asyncio
async def test_model_holding_natural_prop_filters_stale_product_constraints() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request("Create an image of a model holding lotus flowers"))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt
    assert "packaging" not in prompt


@pytest.mark.asyncio
async def test_modal_can_does_not_trigger_product_context() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": "Preserve exact product shape.",
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(
        _image_request("Create an image of a woman who can dance by a lotus lake")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt

@pytest.mark.asyncio
async def test_modal_can_with_holding_natural_prop_does_not_trigger_product_context() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": "Preserve exact product shape.",
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(
        _image_request("Create an image of a woman holding lotus flowers who can dance")
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" not in prompt

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "goal",
    (
        "Create an image of a woman holding a Coke can splashing water",
        "Create an image of a woman holding a Coke can label visible",
    ),
)
async def test_described_packaged_can_keeps_product_fidelity_constraints(goal: str) -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy. "
                            "Keep visible labels exact."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(_image_request(goal))

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "product shape" in prompt
    assert "packaging" in prompt
    assert "visible labels" in prompt


@pytest.mark.asyncio
async def test_non_person_reference_revision_filters_stale_product_dna() -> None:
    class ProductConstraintComposer(PoisonVisualDNAComposer):
        async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
            compiled = await super().compose(spec)
            return compiled.model_copy(
                update={
                    "sections": {
                        **compiled.sections,
                        "constraints_negative_details": (
                            "Preserve exact product shape and packaging hierarchy. "
                            "Keep the product as the clearest focal point. "
                            "Preserve promotional discounts and badge claims."
                        ),
                    }
                }
            )

    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=ProductConstraintComposer(),
        image_generator=generator,
    )
    await executor.execute(
        _image_request(
            "Tạo ảnh chỉnh sửa từ ảnh tham chiếu. Yêu cầu hiện tại: Đổi bầu trời sang hoàng hôn",
            reference_image="media://inbound/22222222-2222-4222-8222-222222222222.jpg",
        )
    )

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "use the provided reference image as the source of truth" in prompt
    assert "packaging hierarchy" not in prompt
    assert "clearest focal point" not in prompt
    assert "promotional discounts" not in prompt
    assert "badge claims" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("compiler_type", "goal"),
    (
        ("portrait_persona", "Create a portrait of a woman holding a serum bottle"),
        ("product", "Create a product hero with a model standing behind it"),
        ("poster_text", 'Create a poster, exact text: "HAI CAKE"'),
        ("reference_edit", "Change the dress to yellow and preserve everything else"),
    ),
)
async def test_visual_compiler_uses_semantic_type_contract_not_keyword_guessing(
    compiler_type: str,
    goal: str,
) -> None:
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=PoisonVisualDNAComposer(),
        image_generator=generator,
    )
    request = _image_request(
        goal,
        reference_image=(
            "media://inbound/11111111-1111-4111-8111-111111111111.jpg"
            if compiler_type == "reference_edit"
            else None
        ),
    ).model_copy(
        update={
            "constraints": (f"visual_compiler:type={compiler_type}",),
            "capability_requirements": ("visual_image_generate",),
        }
    )
    result = await executor.execute(request)

    assert result.artifacts["sections"]["compiler_type"] == compiler_type


@pytest.mark.asyncio
async def test_reference_edit_semantic_contract_encodes_change_only_and_preservation() -> None:
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=PoisonVisualDNAComposer(),
        image_generator=generator,
    )
    request = _image_request(
        "Change the dress to yellow and preserve everything else",
        reference_image="media://inbound/11111111-1111-4111-8111-111111111111.jpg",
    ).model_copy(
        update={
            "constraints": (
                "visual_compiler:type=reference_edit",
                "visual_compiler:preserve_unmentioned=true",
                "visual_compiler:identity_lock=true",
            ),
            "capability_requirements": ("visual_image_generate",),
        }
    )
    await executor.execute(request)

    prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    assert "change only what the current request explicitly asks to change" in prompt
    assert "preserve subject identity" in prompt


@pytest.mark.asyncio
async def test_semantic_visual_compiler_is_stateless_across_unrelated_requests() -> None:
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=PoisonVisualDNAComposer(),
        image_generator=generator,
    )
    candy_request = _image_request("Create a candy poster with a giant lollipop").model_copy(
        update={
            "constraints": ("visual_compiler:type=poster_text",),
            "capability_requirements": ("visual_image_generate",),
        }
    )
    product_request = _image_request("Create a clean serum bottle packshot").model_copy(
        update={
            "constraints": ("visual_compiler:type=product",),
            "capability_requirements": ("visual_image_generate",),
        }
    )

    await executor.execute(candy_request)
    await executor.execute(product_request)

    first_prompt = cast(str, generator.calls[0]["prompt"]).casefold()
    second_prompt = cast(str, generator.calls[1]["prompt"]).casefold()
    assert "candy" in first_prompt
    assert "lollipop" in first_prompt
    assert "candy" not in second_prompt
    assert "lollipop" not in second_prompt


@pytest.mark.asyncio
async def test_poster_text_semantic_compiler_preserves_exact_requested_copy() -> None:
    generator = CaptureImageGenerator()
    executor = VisualForgeRoutingExecutor(
        delegate=cast(Any, object()),
        client=PoisonVisualDNAComposer(),
        image_generator=generator,
    )
    request = _image_request('Create a poster, exact text: "HAI CAKE"').model_copy(
        update={
            "constraints": ("visual_compiler:type=poster_text",),
            "capability_requirements": ("visual_image_generate",),
        }
    )

    result = await executor.execute(request)

    prompt = cast(str, generator.calls[0]["prompt"])
    assert "Visible text must be exactly: HAI CAKE" in prompt
    assert result.artifacts["required_text"] == "HAI CAKE"
