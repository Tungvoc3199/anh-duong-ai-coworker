from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.capabilities import CapabilityDecision, CapabilityKind
from app.context_builder import (
    ContextBuildRequest,
    ContextSection,
    ContextSectionKind,
    ContextTokenBudget,
    ProjectContextSnapshot,
    TaskContextSnapshot,
    Utf8ByteTokenEstimator,
)
from app.persona import PersonaSnapshot
from app.routing import FastRoute, RouteDecision


def _persona() -> PersonaSnapshot:
    return PersonaSnapshot(
        version="1.0",
        content_hash="a" * 64,
        file_order=("IDENTITY.md",),
        files={"IDENTITY.md": "# Identity\n\nÁnh Dương"},
        combined_content="# Identity\n\nÁnh Dương",
    )


def _request(current_request: str = "Tiếp tục CB-1") -> ContextBuildRequest:
    return ContextBuildRequest(
        current_request=current_request,
        persona=_persona(),
        fast_router_decision=RouteDecision(
            route=FastRoute.WORKFLOW,
            rule_id="workflow.action",
            reason="Yêu cầu triển khai.",
        ),
        capability_decision=CapabilityDecision(
            capability=CapabilityKind.CODE_OPERATION,
            source_route=FastRoute.WORKFLOW,
            reason_code="workflow.code",
            matched_signals=("action:build",),
        ),
    )


def test_default_budget_reserves_leave_twelve_thousand_usable_tokens() -> None:
    budget = ContextTokenBudget()

    assert budget.context_window_tokens == 16_000
    assert budget.response_reserve_tokens == 3_000
    assert budget.runtime_reserve_tokens == 1_000
    assert budget.usable_context_tokens == 12_000
    assert (
        budget.persona_soft_tokens
        + budget.routing_soft_tokens
        + budget.task_soft_tokens
        + budget.project_soft_tokens
        + budget.memory_soft_tokens
    ) == 12_000


def test_custom_budget_computes_usable_tokens_from_reserves() -> None:
    budget = ContextTokenBudget(
        context_window_tokens=4_096,
        response_reserve_tokens=512,
        runtime_reserve_tokens=256,
    )

    assert budget.usable_context_tokens == 3_328


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"context_window_tokens": 0}, "greater than 0"),
        ({"response_reserve_tokens": -1}, "greater than or equal to 0"),
        ({"runtime_reserve_tokens": -1}, "greater than or equal to 0"),
        (
            {
                "context_window_tokens": 1_000,
                "response_reserve_tokens": 800,
                "runtime_reserve_tokens": 200,
            },
            "usable_context_tokens must be greater than 0",
        ),
    ],
)
def test_invalid_budget_is_rejected(
    values: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ContextTokenBudget(**values)


def test_blank_current_request_is_rejected_instead_of_being_dropped() -> None:
    with pytest.raises(ValidationError, match="current_request cannot be blank"):
        _request(" \n\t ")


def test_input_snapshots_and_sections_are_frozen() -> None:
    project = ProjectContextSnapshot(
        identity="anh-duong-core",
        goal="Build AI coworker core",
        architecture_constraints=("Không đổi database schema",),
    )
    task = TaskContextSnapshot(
        identity="CB-1",
        active_goal="Build Context Builder v1",
        constraints=("Không gọi LLM",),
    )
    section = ContextSection(
        kind=ContextSectionKind.CURRENT_REQUEST,
        content="Tiếp tục CB-1",
        priority=100,
        estimated_tokens=3,
        source_refs=("request:current",),
    )

    with pytest.raises(ValidationError, match="frozen"):
        project.identity = "mutated"
    with pytest.raises(ValidationError, match="frozen"):
        task.active_goal = "mutated"
    with pytest.raises(ValidationError, match="frozen"):
        section.content = "mutated"


def test_utf8_estimator_is_deterministic_for_vietnamese_text() -> None:
    estimator = Utf8ByteTokenEstimator()

    assert estimator.estimate("") == 0
    assert estimator.estimate("Ánh Dương") == 3
    assert estimator.estimate("Ánh Dương") == estimator.estimate("Ánh Dương")


def test_request_uses_existing_router_and_persona_contracts() -> None:
    request = _request("  Tiếp tục CB-1  ")

    assert request.current_request == "Tiếp tục CB-1"
    assert request.persona is not None
    assert request.fast_router_decision.route is FastRoute.WORKFLOW
    assert request.capability_decision.capability is CapabilityKind.CODE_OPERATION

