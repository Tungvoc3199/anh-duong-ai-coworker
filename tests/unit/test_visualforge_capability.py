from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.capabilities import CapabilityKind, CapabilityRouter
from app.openclaw.models import OpenClawExecutionRequest, OpenClawExecutionResult
from app.orchestration.workflow import WorkflowResolver
from app.policy import RiskLevel
from app.routing import FastRoute, FastRouter


def _request(goal: str) -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_visual",
        run_id="run_visual",
        attempt=1,
        idempotency_key="run_visual:1",
        project_id="proj_visual",
        goal=goal,
        mode="quick",
        workspace="/tmp",
    )


def test_visual_prompt_request_routes_to_local_visual_capability() -> None:
    goal = (
        'Dùng VisualForge làm prompt ảnh TikTok bán serum, 9:16, '
        'text chính xác "DƯỠNG SÁNG DA – GIẢM 50% HÔM NAY".'
    )
    route = FastRouter().route(goal)
    capability = CapabilityRouter().route(route, goal)

    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.VISUAL_PROMPT_COMPOSE


def test_visualforge_question_stays_direct_conversation() -> None:
    goal = "VisualForge là gì và dùng như nào?"
    route = FastRouter().route(goal)
    capability = CapabilityRouter().route(route, goal)

    assert route.route is FastRoute.DIRECT
    assert capability.capability is CapabilityKind.CONVERSATIONAL_RESPONSE


def test_visual_prompt_workflow_is_read_only_without_approval() -> None:
    action, risk, constraints = WorkflowResolver._action(
        "dùng visualforge tạo prompt ảnh sản phẩm",
        CapabilityKind.VISUAL_PROMPT_COMPOSE,
    )
    assert action == "compose_visual_prompt"
    assert risk is RiskLevel.READ_ONLY
    assert "read_only" in constraints
    assert "no_external_network" in constraints


def test_visual_prompt_parser_preserves_exact_text_and_selects_template() -> None:
    from app.visualforge import VisualPromptParser

    goal = (
        'Dùng VisualForge làm prompt ảnh TikTok bán serum, 9:16, '
        'text chính xác "DƯỠNG SÁNG DA – GIẢM 50% HÔM NAY".'
    )
    spec = VisualPromptParser().parse(goal)

    assert spec.template == "tiktok-affiliate-hook"
    assert spec.adapter == "gpt-image"
    assert spec.aspect_ratio == "9:16"
    assert spec.required_text == "DƯỠNG SÁNG DA – GIẢM 50% HÔM NAY"
    assert spec.query == "beauty ecommerce serum skincare"
    assert spec.brief == goal


class FakeDelegate:
    def __init__(self) -> None:
        self.requests: list[OpenClawExecutionRequest] = []

    async def execute(self, request: OpenClawExecutionRequest) -> OpenClawExecutionResult:
        self.requests.append(request)
        return OpenClawExecutionResult(outcome="completed", summary="delegated")


class FakeVisualForgeClient:
    def __init__(self) -> None:
        self.specs: list[Any] = []

    async def compose(self, spec: Any) -> Any:
        from app.visualforge import VisualForgeCompiledPrompt

        self.specs.append(spec)
        return VisualForgeCompiledPrompt(
            prompt="COMPILED VISUAL PROMPT",
            adapter="gpt-image",
            required_text=spec.required_text,
            provenance_notes=("dna-1; source=local; license=MIT",),
            sections={"task_subject": "serum campaign"},
        )


@pytest.mark.asyncio
async def test_visual_executor_intercepts_without_openclaw() -> None:
    from app.visualforge import VisualForgeRoutingExecutor

    delegate = FakeDelegate()
    client = FakeVisualForgeClient()
    executor = VisualForgeRoutingExecutor(delegate=delegate, client=client)
    result = await executor.execute(_request(
        'Dùng VisualForge tạo prompt ảnh TikTok serum 9:16, text "GIẢM 50%"'
    ))

    assert delegate.requests == []
    assert len(client.specs) == 1
    assert result.outcome == "completed"
    assert result.profile == "visualforge-v0.2"
    assert isinstance(result.artifacts, dict)
    assert result.artifacts["visual_prompt"] == "COMPILED VISUAL PROMPT"
    assert result.artifacts["required_text"] == "GIẢM 50%"
    assert "GIẢM 50%" in result.summary


@pytest.mark.asyncio
async def test_non_visual_request_delegates_unchanged() -> None:
    from app.visualforge import VisualForgeRoutingExecutor

    delegate = FakeDelegate()
    client = FakeVisualForgeClient()
    executor = VisualForgeRoutingExecutor(delegate=delegate, client=client)
    request = _request("Chạy pytest cho dự án hiện tại")

    result = await executor.execute(request)

    assert result.summary == "delegated"
    assert delegate.requests == [request]
    assert client.specs == []


def test_visualforge_settings_pin_current_release() -> None:
    from app.config import Settings

    settings = Settings()
    assert settings.visualforge_root == Path("/home/thadc/AIOS/visualforge")
    assert settings.visualforge_expected_commit == (
        "aac8cbf6bf21f03d2338d81da8764e990055c4d2"
    )


def test_generic_visual_prompt_request_uses_visualforge_capability() -> None:
    goal = 'Tạo prompt ảnh poster khai trương, text "KHAI TRƯƠNG - GIẢM 30%"'
    route = FastRouter().route(goal)
    capability = CapabilityRouter().route(route, goal)

    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.VISUAL_PROMPT_COMPOSE


def test_visual_prompt_guidance_question_stays_direct() -> None:
    goal = "Hướng dẫn anh viết prompt ảnh như nào cho đẹp?"
    route = FastRouter().route(goal)
    capability = CapabilityRouter().route(route, goal)

    assert route.route is FastRoute.DIRECT
    assert capability.capability is CapabilityKind.CONVERSATIONAL_RESPONSE


def test_visualforge_repo_coding_request_is_not_visual_prompt_capability() -> None:
    goal = "Sửa code Python trong repo VisualForge"
    route = FastRouter().route(goal)
    capability = CapabilityRouter().route(route, goal)

    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.CODE_OPERATION


@pytest.mark.asyncio
async def test_visualforge_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    from app.visualforge import (
        VisualForgeClient,
        VisualForgeRuntimeError,
        VisualPromptParser,
    )

    class Client(VisualForgeClient):
        def _validate_root(self) -> None:
            return None

        async def _git_head(self) -> str:
            return "deadbeef"

        async def _git_status(self) -> str:
            return ""

    client = Client(root=tmp_path, expected_commit="expected")
    with pytest.raises(VisualForgeRuntimeError) as caught:
        await client.compose(VisualPromptParser().parse("Tạo prompt ảnh sản phẩm"))
    assert caught.value.code == "visualforge_revision_mismatch"


def test_visual_prompt_compound_external_request_keeps_external_capability() -> None:
    goal = 'Tạo prompt ảnh sản phẩm rồi gửi qua Telegram'
    route = FastRouter().route(goal)
    capability = CapabilityRouter().route(route, goal)

    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.EXTERNAL_COMMUNICATION


def test_visual_prompt_compound_file_request_keeps_file_capability() -> None:
    goal = 'Tạo prompt ảnh sản phẩm rồi ghi vào file prompt.txt'
    route = FastRouter().route(goal)
    capability = CapabilityRouter().route(route, goal)

    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.FILE_OPERATION


def test_tiktok_serum_parser_keeps_beauty_subject_in_search_query() -> None:
    from app.visualforge import VisualPromptParser

    spec = VisualPromptParser().parse(
        'Tạo prompt ảnh TikTok bán serum dưỡng sáng, text "GIẢM 50%"'
    )

    assert spec.template == "tiktok-affiliate-hook"
    assert "beauty" in spec.query
    assert "serum" in spec.query
    assert "ecommerce" in spec.query

@pytest.mark.asyncio
async def test_visualforge_client_checks_untracked_files(tmp_path: Path) -> None:
    from app.visualforge import VisualForgeClient

    calls: list[list[str]] = []

    class Client(VisualForgeClient):
        async def _run(self, argv: list[str], *, use_pythonpath: bool = True) -> str:
            calls.append(argv)
            return ""

    client = Client(root=tmp_path, expected_commit="abc")
    await client._git_status()

    assert calls
    assert "--untracked-files=all" in calls[0]


def test_visualforge_client_uses_isolated_python_argv(tmp_path: Path) -> None:
    from app.visualforge import VisualForgeClient, VisualPromptParser

    client = VisualForgeClient(root=tmp_path, expected_commit="abc")
    spec = VisualPromptParser().parse('Tạo prompt ảnh serum, text "GIẢM 50%"')
    argv = client._compose_argv(spec)

    assert argv[:4] == ["unshare", "-Urn", "--", "/usr/bin/python3"]
    assert argv[4] == "-I"
    assert str(tmp_path / "src") in argv
    assert "-m" not in argv[:7]

def test_visual_prompt_parser_extracts_noi_dung_copy() -> None:
    from app.visualforge import VisualPromptParser

    spec = VisualPromptParser().parse(
        'Tạo prompt ảnh sản phẩm, nội dung "MUA 1 TẶNG 1"'
    )

    assert spec.required_text == "MUA 1 TẶNG 1"


def test_visual_prompt_parser_uses_single_unlabelled_quote_as_visible_copy() -> None:
    from app.visualforge import VisualPromptParser

    spec = VisualPromptParser().parse(
        'Tạo prompt ảnh poster khai trương "KHAI TRƯƠNG -30%"'
    )

    assert spec.required_text == "KHAI TRƯƠNG -30%"


def test_visual_prompt_parser_rejects_ambiguous_unlabelled_quotes() -> None:
    from app.visualforge import VisualPromptParseError, VisualPromptParser

    with pytest.raises(VisualPromptParseError):
        VisualPromptParser().parse(
            'Tạo prompt ảnh poster "SALE" theo phong cách "minimal"'
        )


def test_visualforge_compose_argv_enforces_network_namespace(tmp_path: Path) -> None:
    from app.visualforge import VisualForgeClient, VisualPromptParser

    client = VisualForgeClient(root=tmp_path, expected_commit="abc")
    spec = VisualPromptParser().parse(
        'Tạo prompt ảnh serum, text "GIẢM 50%"'
    )
    argv = client._compose_argv(spec)

    assert argv[:4] == ["unshare", "-Urn", "--", "/usr/bin/python3"]
    assert "-I" in argv[:6]


def test_visual_prompt_parser_treats_negated_text_as_no_visible_copy() -> None:
    from app.visualforge import VisualPromptParser

    goal = (
        "Tạo cho anh đúng 1 ảnh thời trang nữ cao cấp để đăng Facebook. "
        "Yêu cầu: Người mẫu nữ mặc váy đỏ burgundy hiện đại, thanh lịch "
        "Background studio màu be tối giản Ánh sáng editorial cao cấp, "
        "da và chất liệu váy chân thực Bố cục toàn thân, sang trọng "
        "Tỷ lệ dọc 4:5 Không chữ, không logo, không watermark "
        "Chỉ tạo và gửi đúng 1 ảnh, không gửi trùng Tự thực hiện luôn, không hỏi lại."
    )

    spec = VisualPromptParser().parse(goal)

    assert spec.required_text == ""
    assert spec.aspect_ratio == "4:5"


@pytest.mark.parametrize(
    "goal",
    [
        "Tạo prompt ảnh poster, text GIẢM 50% HÔM NAY",
        "Tạo prompt ảnh poster, headline SALE 50%",
        "Tạo prompt ảnh poster, chữ SALE 50%",
        "Tạo prompt ảnh poster, copy MUA 1 TẶNG 1",
    ],
)
def test_visual_prompt_parser_rejects_unquoted_visible_copy_label(goal: str) -> None:
    from app.visualforge import VisualPromptParseError, VisualPromptParser

    with pytest.raises(VisualPromptParseError) as caught:
        VisualPromptParser().parse(goal)

    assert caught.value.code == "visualforge_visible_text_unquoted"


def test_visual_prompt_parser_accepts_vietnamese_exact_display_label() -> None:
    from app.visualforge import VisualPromptParser

    goal = (
        'Dùng VisualForge tạo prompt ảnh TikTok bán serum dưỡng sáng, tỷ lệ 9:16. '
        'Text hiển thị chính xác: "DƯỠNG SÁNG DA – GIẢM 50% HÔM NAY"'
    )
    spec = VisualPromptParser().parse(goal)

    assert spec.required_text == "DƯỠNG SÁNG DA – GIẢM 50% HÔM NAY"
    assert spec.aspect_ratio == "9:16"
