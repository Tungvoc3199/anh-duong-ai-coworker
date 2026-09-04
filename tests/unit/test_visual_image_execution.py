from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from app.async_tasks import AsyncRunStatus, AsyncTaskMode, AsyncTaskRun, NotificationStatus
from app.openclaw import OpenClawNotifier, OpenClawTransportError
from app.openclaw.image_generator import (
    OpenClawImageArtifact,
    OpenClawImageGenerator,
)
from app.openclaw.models import OpenClawExecutionRequest, OpenClawExecutionResult
from app.visualforge import VisualForgeCompiledPrompt, VisualForgeRoutingExecutor

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def _allow_subscription_preflight_for_existing_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allowed(_self: OpenClawImageGenerator, _run_id: str) -> None:
        return None

    monkeypatch.setattr(
        OpenClawImageGenerator,
        "_require_subscription_route_ready",
        allowed,
        raising=False,
    )


def _request(goal: str) -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_img",
        run_id="run_img_exec",
        attempt=1,
        idempotency_key="run_img_exec:1",
        project_id="proj_img",
        goal=goal,
        mode="quick",
        workspace="/tmp",
        dod_criteria=("deliver one generated image",),
    )


class FakeDelegate:
    def __init__(self) -> None:
        self.requests: list[OpenClawExecutionRequest] = []

    async def execute(self, request: OpenClawExecutionRequest) -> OpenClawExecutionResult:
        self.requests.append(request)
        return OpenClawExecutionResult(outcome="completed", summary="delegated")


class FakeComposer:
    def __init__(self) -> None:
        self.specs: list[Any] = []

    async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
        self.specs.append(spec)
        return VisualForgeCompiledPrompt(
            prompt="COMPILED IMAGE PROMPT WITH SAFE AREA",
            adapter="gpt-image",
            required_text=spec.required_text,
            provenance_notes=("dna-1; source=local; license=MIT",),
            sections={"task_subject": "serum"},
        )


@pytest.mark.asyncio
async def test_native_generator_is_one_call_and_recovers_same_artifact(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        media_path = "/media/run_img_exec.png"
        (tmp_path / "run_img_exec.png").write_bytes(PNG_BYTES)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "details": {
                        "provider": "openai",
                        "model": "gpt-image-2",
                        "count": 1,
                        "paths": [media_path],
                        "attachments": [
                            {
                                "path": media_path,
                                "mimeType": "image/png",
                                "size": len(PNG_BYTES),
                                "width": 1,
                                "height": 1,
                            }
                        ],
                    },
                },
            },
        )

    generator = OpenClawImageGenerator(
        base_url="http://openclaw",
        host_output_root=tmp_path,
        container_output_root="/media",
        auth_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    first = await generator.generate(
        prompt="one image",
        run_id="run_img_exec",
        aspect_ratio="9:16",
    )
    second = await generator.generate(
        prompt="one image",
        run_id="run_img_exec",
        aspect_ratio="9:16",
    )

    assert len(requests) == 1
    args = requests[0]["args"]
    assert args["count"] == 1
    assert args["model"] == "openai/gpt-image-2"
    assert args["outputFormat"] == "png"
    assert args["filename"] == "run_img_exec.png"
    assert requests[0]["idempotencyKey"] == "visual-image:run_img_exec"
    assert first.recovered is False
    assert second.recovered is True
    assert first.sha256 == second.sha256
    assert first.media_path.endswith("run_img_exec.png")


@pytest.mark.asyncio
async def test_native_generator_waits_for_detached_native_artifact(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        artifact_name = "run_async---01234567-89ab-cdef-0123-456789abcdef.png"
        (tmp_path / artifact_name).write_bytes(PNG_BYTES)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "details": {
                        "async": True,
                        "status": "started",
                        "provider": "openai",
                        "model": "gpt-image-2",
                    },
                },
            },
        )

    generator = OpenClawImageGenerator(
        base_url="http://openclaw",
        host_output_root=tmp_path,
        container_output_root="/media",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )

    first = await generator.generate(prompt="one image", run_id="run_async")
    second = await generator.generate(prompt="one image", run_id="run_async")

    assert len(requests) == 1
    assert first.recovered is True
    assert second.recovered is True
    assert first.sha256 == second.sha256
    assert first.media_path.endswith("run_async---01234567-89ab-cdef-0123-456789abcdef.png")


@pytest.mark.asyncio
async def test_native_generator_rejects_invalid_png_without_regeneration(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        media_path = "/media/run_invalid.png"
        (tmp_path / "run_invalid.png").write_bytes(b"not png")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "details": {
                        "provider": "openai",
                        "model": "gpt-image-2",
                        "count": 1,
                        "paths": [media_path],
                    },
                },
            },
        )

    generator = OpenClawImageGenerator(
        base_url="http://openclaw",
        host_output_root=tmp_path,
        container_output_root="/media",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpenClawTransportError) as caught:
        await generator.generate(prompt="one", run_id="run_invalid")
    assert caught.value.code == "image_invalid_png"
    assert calls == 1


def _ready_subscription_route_catalog() -> dict[str, Any]:
    return {
        "providers": [
            {
                "id": "openai",
                "configured": True,
                "defaultModel": "gpt-image-2",
                "models": ["gpt-image-2", "gpt-image-1.5"],
            }
        ]
    }


def test_subscription_route_catalog_accepts_openclaw_2026_7_1_openai_catalog() -> None:
    OpenClawImageGenerator._validate_subscription_route_catalog(
        _ready_subscription_route_catalog()
    )


@pytest.mark.parametrize(
    "provider",
    [
        {
            "id": "openai", "configured": False, "selected": True,
            "defaultModel": "gpt-image-2", "models": ["gpt-image-2"],
        },
        {
            "id": "openai", "configured": True, "selected": False,
            "defaultModel": "gpt-image-2", "models": ["gpt-image-2"],
        },
        {
            "id": "openai", "configured": True, "selected": None,
            "defaultModel": "gpt-image-2", "models": ["gpt-image-2"],
        },
        {
            "id": "openai", "configured": True, "selected": 0,
            "defaultModel": "gpt-image-2", "models": ["gpt-image-2"],
        },
        {
            "id": "openai", "configured": True, "selected": "false",
            "defaultModel": "gpt-image-2", "models": ["gpt-image-2"],
        },
        {
            "id": "openai", "configured": True, "selected": True,
            "defaultModel": "gpt-image-1.5", "models": ["gpt-image-2"],
        },
        {
            "id": "openai", "configured": True, "selected": True,
            "defaultModel": "gpt-image-2", "models": ["gpt-image-1.5"],
        },
    ],
)
def test_subscription_route_catalog_rejects_unready_route(provider: dict[str, Any]) -> None:
    with pytest.raises(OpenClawTransportError) as caught:
        OpenClawImageGenerator._validate_subscription_route_catalog({"providers": [provider]})
    assert caught.value.code == "image_subscription_route_unverified"
    assert caught.value.retryable is False
    assert caught.value.uncertain_side_effect is False


@pytest.mark.asyncio
async def test_subscription_route_catalog_probe_uses_http_gateway_and_same_session(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"ok": True, "result": {"details": _ready_subscription_route_catalog()}},
        )

    generator = OpenClawImageGenerator(
        base_url="http://openclaw",
        host_output_root=tmp_path,
        container_output_root="/media",
        auth_token="gateway-test-token",
        transport=httpx.MockTransport(handler),
    )
    catalog = await generator._read_subscription_route_catalog("run_route_probe")
    assert catalog["providers"][0]["id"] == "openai"
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload == {
        "name": "image_generate",
        "args": {"action": "list"},
        "sessionKey": "agent:main:cron:anh-duong-image:run:run_route_probe",
    }
    assert requests[0].headers["Authorization"] == "Bearer gateway-test-token"


@pytest.mark.asyncio
async def test_native_generator_blocks_unready_subscription_route_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def blocked(_self: OpenClawImageGenerator, _run_id: str) -> None:
        raise OpenClawTransportError(
            "image_subscription_route_unverified",
            "Managed subscription image route is not ready.",
            retryable=False,
        )

    monkeypatch.setattr(OpenClawImageGenerator, "_require_subscription_route_ready", blocked)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    generator = OpenClawImageGenerator(
        base_url="http://openclaw",
        host_output_root=tmp_path,
        container_output_root="/media",
        auth_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpenClawTransportError) as caught:
        await generator.generate(prompt="one image", run_id="run_route_block")
    assert caught.value.code == "image_subscription_route_unverified"
    assert calls == 0


@pytest.mark.asyncio
async def test_native_generator_rejects_any_native_fallback_attempt(tmp_path: Path) -> None:
    media_path = "/media/run_fallback.png"

    def handler(_request: httpx.Request) -> httpx.Response:
        (tmp_path / "run_fallback.png").write_bytes(PNG_BYTES)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "details": {
                        "provider": "openai",
                        "model": "gpt-image-2",
                        "count": 1,
                        "paths": [media_path],
                        "attempts": [
                            {
                                "provider": "openrouter",
                                "model": "paid-image",
                                "error": "fallback attempted",
                            }
                        ],
                    }
                },
            },
        )

    generator = OpenClawImageGenerator(
        base_url="http://openclaw",
        host_output_root=tmp_path,
        container_output_root="/media",
        auth_token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(OpenClawTransportError) as caught:
        await generator.generate(prompt="one image", run_id="run_fallback")

    assert caught.value.code == "image_fallback_forbidden"


class FakeImageGenerator:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.calls: list[dict[str, str]] = []

    async def generate(
        self, *, prompt: str, run_id: str, aspect_ratio: str = ""
    ) -> OpenClawImageArtifact:
        self.calls.append({"prompt": prompt, "run_id": run_id, "aspect_ratio": aspect_ratio})
        return OpenClawImageArtifact(
            path=self.path,
            media_path="/home/node/.openclaw/media/anh-duong/run_img_exec.png",
            sha256="a" * 64,
            mime_type="image/png",
            size_bytes=123,
            width=1024,
            height=1536,
            provider="openai",
            model="gpt-image-2",
            requested_aspect_ratio=aspect_ratio,
            rendered_size="1024x1536",
            recovered=False,
        )


@pytest.mark.asyncio
async def test_visual_image_executor_compiles_then_generates_once(tmp_path: Path) -> None:
    delegate = FakeDelegate()
    composer = FakeComposer()
    image_generator = FakeImageGenerator(tmp_path / "run_img_exec.png")
    executor = VisualForgeRoutingExecutor(
        delegate=delegate,
        client=composer,
        image_generator=image_generator,
    )

    result = await executor.execute(
        _request('Tạo ảnh TikTok serum 9:16, text chính xác "DƯỠNG SÁNG DA".')
    )

    assert delegate.requests == []
    assert len(composer.specs) == 1
    assert image_generator.calls == [
        {
            "prompt": "COMPILED IMAGE PROMPT WITH SAFE AREA",
            "run_id": "run_img_exec",
            "aspect_ratio": "9:16",
        }
    ]
    assert result.outcome == "completed"
    assert result.provider == "openai"
    assert result.model == "gpt-image-2"
    assert result.profile == "visualforge-v0.2+openclaw-image"
    assert isinstance(result.artifacts, dict)
    image = cast(dict[str, Any], result.artifacts["image"])
    assert image["media_path"].endswith("run_img_exec.png")
    assert result.verification["image_artifact_verified"] is True


@pytest.mark.asyncio
async def test_prompt_only_executor_does_not_call_image_generator(tmp_path: Path) -> None:
    delegate = FakeDelegate()
    composer = FakeComposer()
    image_generator = FakeImageGenerator(tmp_path / "unused.png")
    executor = VisualForgeRoutingExecutor(
        delegate=delegate,
        client=composer,
        image_generator=image_generator,
    )

    result = await executor.execute(_request("Tạo prompt ảnh sản phẩm"))

    assert result.provider == "local"
    assert image_generator.calls == []


def _notification_run() -> AsyncTaskRun:
    now = datetime(2026, 8, 31, 15, 0, tzinfo=UTC)
    return AsyncTaskRun(
        id="run_img_exec",
        task_id="task_img",
        status=AsyncRunStatus.COMPLETED,
        mode=AsyncTaskMode.BUILD,
        goal="Generate image",
        workspace="/tmp",
        request_json="{}",
        checkpoint_json=None,
        result_json=json.dumps(
            {
                "outcome": "completed",
                "summary": "Ảnh đã tạo xong bằng VisualForge + GPT-Image-2.",
                "artifacts": {
                    "image": {
                        "path": "/home/thadc/.openclaw/media/anh-duong/run_img_exec.png",
                        "media_path": "/home/node/.openclaw/media/anh-duong/run_img_exec.png",
                        "sha256": "a" * 64,
                        "mime_type": "image/png",
                        "size_bytes": 12345,
                    }
                },
                "verification": {"image_artifact_verified": True},
            }
        ),
        attempt=1,
        max_attempts=3,
        run_after=now,
        lease_owner=None,
        lease_expires_at=None,
        idempotency_key="telegram:image:1",
        external_run_id=None,
        last_error_code=None,
        last_error_message=None,
        source_chat_id="7535966424",
        notification_status=NotificationStatus.PENDING,
        notification_attempts=0,
        created_at=now,
        updated_at=now,
        version=1,
    )


@pytest.mark.asyncio
async def test_notifier_reuses_verified_media_and_idempotency_key() -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"messageId": "99"}})

    notifier = OpenClawNotifier(
        base_url="http://127.0.0.1:18789",
        notification_path="/tools/invoke",
        auth_token="test-token",
        transport=httpx.MockTransport(handler),
    )
    await notifier.send_final(_notification_run())
    await notifier.send_final(_notification_run())

    assert len(captured) == 2
    first = cast(dict[str, Any], captured[0]["args"])
    second = cast(dict[str, Any], captured[1]["args"])
    assert first["media"] == "/home/node/.openclaw/media/anh-duong/run_img_exec.png"
    assert first["mimeType"] == "image/png"
    assert first["idempotencyKey"] == "notify:run_img_exec:completed"
    assert second["media"] == first["media"]
    assert second["idempotencyKey"] == first["idempotencyKey"]
    assert "GPT-Image-2" in first["message"]

@pytest.mark.asyncio
async def test_native_generator_remote_protocol_failure_is_uncertain(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("peer closed after dispatch")

    generator = OpenClawImageGenerator(
        base_url="http://openclaw",
        host_output_root=tmp_path,
        container_output_root="/media",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(OpenClawTransportError) as caught:
        await generator.generate(prompt="one image", run_id="run_uncertain")

    assert caught.value.code == "image_transport_error"
    assert caught.value.retryable is True
    assert caught.value.uncertain_side_effect is True


@pytest.mark.asyncio
async def test_notifier_rejects_control_character_in_image_media_path() -> None:
    run = _notification_run().model_copy(update={
        "result_json": _notification_run().result_json.replace(
            "run_img_exec.png", "run_img_exec\\n.png"
        )
    })
    notifier = OpenClawNotifier(base_url="http://127.0.0.1:18789")

    with pytest.raises(OpenClawTransportError) as caught:
        await notifier.send_final(run)

    assert caught.value.code == "notification_artifact_invalid"

@pytest.mark.asyncio
async def test_notifier_rejects_decoded_control_character_in_image_media_path() -> None:
    payload = json.loads(_notification_run().result_json)
    payload["artifacts"]["image"]["media_path"] = (
        "/home/node/.openclaw/media/anh-duong/run_img_exec\n.png"
    )
    run = _notification_run().model_copy(update={"result_json": json.dumps(payload)})
    notifier = OpenClawNotifier(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"ok": True, "result": {}})
        ),
    )

    with pytest.raises(OpenClawTransportError) as caught:
        await notifier.send_final(run)

    assert caught.value.code == "notification_artifact_invalid"

@pytest.mark.asyncio
async def test_notifier_fails_closed_when_image_profile_has_no_verified_media() -> None:
    payload = json.loads(_notification_run().result_json)
    payload["profile"] = "visualforge-v0.2+openclaw-image"
    payload["artifacts"].pop("image")
    run = _notification_run().model_copy(update={"result_json": json.dumps(payload)})
    notifier = OpenClawNotifier(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"ok": True, "result": {}})
        ),
    )

    with pytest.raises(OpenClawTransportError) as caught:
        await notifier.send_final(run)

    assert caught.value.code == "notification_artifact_invalid"
