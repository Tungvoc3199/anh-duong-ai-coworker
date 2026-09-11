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

    await executor.execute(_image_request(goal, reference_image=reference))

    assert len(generator.calls) == 1
    call = generator.calls[0]
    assert call["reference_image"] == reference
    prompt = cast(str, call["prompt"])
    assert "Đổi váy sang màu vàng" in prompt
    assert "preserve" in prompt.casefold() or "giữ nguyên" in prompt.casefold()
    for stale in ("chupa", "lollipop", "candy", "billboard", "fmcg", "mumbai"):
        assert stale not in prompt.casefold()


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
