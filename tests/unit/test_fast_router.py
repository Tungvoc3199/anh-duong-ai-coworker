import pytest
from pydantic import ValidationError

from app.routing import FastRoute, FastRouter, RouteDecision


@pytest.mark.parametrize(
    "text",
    [
        "Xin chào!",
        "Chào buổi sáng, Ánh Dương.",
        "Chào bạn, khỏe không?",
        "Cảm ơn bạn.",
        "OK",
        "Đã rõ.",
        "Got it.",
        "Vâng, tôi hiểu rồi.",
        "Sounds good!",
        "Thanks so much.",
    ],
)
def test_simple_conversation_routes_direct(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.DIRECT


@pytest.mark.parametrize(
    "text",
    [
        "Hãy tìm trong bộ nhớ điều tôi đã lưu về Project Atlas.",
        "Bạn có nhớ tôi đã nói gì về ngân sách không?",
        "Cho tôi biết thông tin đã lưu về Project Atlas.",
        "Nhớ lại sở thích giao diện của tôi.",
        "Search memory for the deployment note.",
        "Recall my stored preference for dark mode.",
        "What have I saved about deployments?",
        "What did I say about the release date?",
    ],
)
def test_stored_information_requests_route_memory(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.MEMORY


@pytest.mark.parametrize(
    "text",
    [
        "Cho tôi xem trạng thái Core.",
        "Dự án Atlas thế nào?",
        "Tiến độ Project Atlas thế nào?",
        "Task FR-1 đang ở trạng thái nào?",
        "Kiểm tra health của Ánh Dương Core.",
        "How is Core?",
        "Show me the current Core status.",
        "What is the progress of project Atlas?",
    ],
)
def test_status_requests_route_core_read(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.CORE_READ


@pytest.mark.parametrize(
    "text",
    [
        "Hãy lập kế hoạch cho FR-1.",
        "Tạo file bao-cao.md.",
        "Sửa README và chạy pytest.",
        "Triển khai Fast Router.",
        "Build the new routing module.",
        "Delete the obsolete file.",
        "Send the status report by email.",
    ],
)
def test_action_requests_route_workflow(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.WORKFLOW


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \t\n",
    ],
)
def test_empty_requests_fail_closed(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.WORKFLOW


@pytest.mark.parametrize(
    "text",
    [
        "Màu tím.",
        "Could you help me with this?",
        "Phân tích việc này.",
    ],
)
def test_unknown_non_action_requests_route_direct(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.DIRECT
    assert decision.rule_id == "routing.direct.no_explicit_execution_intent"


@pytest.mark.parametrize(
    "text",
    [
        "Cảm ơn, hãy tạo file báo cáo.",
        "Tìm trong memory rồi sửa README.",
        "Xem trạng thái Task FR-1 và cập nhật nó thành completed.",
    ],
)
def test_side_effect_intent_takes_precedence(text: str) -> None:
    decision = FastRouter().route(text)

    assert decision.route is FastRoute.WORKFLOW
    assert decision.rule_id == "routing.workflow.explicit_action"


def test_empty_input_uses_explicit_fail_closed_rule() -> None:
    decision = FastRouter().route(" \n\t ")

    assert decision == RouteDecision(
        route=FastRoute.WORKFLOW,
        rule_id="routing.workflow.empty_input",
        reason="Empty input is routed to workflow for safe handling.",
    )


def test_route_decision_is_immutable() -> None:
    decision = FastRouter().route("Xin chào")

    with pytest.raises(ValidationError):
        decision.route = FastRoute.WORKFLOW


def test_routing_package_exports_public_contract() -> None:
    from app.routing import FastRoute as ExportedFastRoute
    from app.routing import FastRouter as ExportedFastRouter
    from app.routing import RouteDecision as ExportedRouteDecision

    assert ExportedFastRoute is FastRoute
    assert ExportedFastRouter is FastRouter
    assert ExportedRouteDecision is RouteDecision
