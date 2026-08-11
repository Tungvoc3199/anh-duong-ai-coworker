from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.capabilities import CapabilityDecision, CapabilityKind
from app.context_builder import ContextBundle, ContextTokenBudget
from app.orchestration import (
    CoreRequest,
    PersonaReference,
    PreparedRequest,
    RequestProvenance,
)
from app.routing import FastRoute, RouteDecision


def _prepared_request() -> PreparedRequest:
    budget = ContextTokenBudget()
    return PreparedRequest(
        request_id="req_test",
        normalized_text="Xin chào!",
        persona=PersonaReference(
            version="1.0",
            content_hash="a" * 64,
        ),
        route_decision=RouteDecision(
            route=FastRoute.DIRECT,
            rule_id="routing.direct.simple_conversation",
            reason="Simple conversation.",
        ),
        capability_decision=CapabilityDecision(
            capability=CapabilityKind.CONVERSATIONAL_RESPONSE,
            source_route=FastRoute.DIRECT,
            reason_code="capability.direct.conversational_response",
            matched_signals=("route:direct",),
        ),
        context=ContextBundle(
            sections=(),
            rendered_context="",
            token_budget=budget,
            estimated_tokens=0,
            remaining_tokens=budget.usable_context_tokens,
        ),
        project_id=None,
        task_id=None,
        execution_required=False,
        warnings=(),
        provenance=RequestProvenance(
            persona_version="1.0",
            persona_content_hash="a" * 64,
            route_rule_id="routing.direct.simple_conversation",
            capability_reason_code=(
                "capability.direct.conversational_response"
            ),
            context_source_refs=(),
        ),
        created_at=datetime(2026, 8, 1, 3, 0, tzinfo=UTC),
    )


def test_core_request_normalizes_text_and_defaults_internal_origin() -> None:
    request = CoreRequest(text="  Xin   chào! \n")

    assert request.text == "Xin chào!"
    assert request.request_id is None
    assert request.channel == "internal"
    assert request.actor == "internal"
    assert request.project_id is None
    assert request.task_id is None
    assert request.memory_scope_id is None


def test_core_request_rejects_blank_text() -> None:
    with pytest.raises(ValidationError, match="text cannot be blank"):
        CoreRequest(text=" \n\t ")


def test_request_and_prepared_response_are_immutable() -> None:
    request = CoreRequest(text="Xin chào")
    prepared = _prepared_request()

    with pytest.raises(ValidationError, match="frozen"):
        request.text = "mutated"
    with pytest.raises(ValidationError, match="frozen"):
        prepared.normalized_text = "mutated"


def test_prepared_request_requires_timezone_aware_created_at() -> None:
    prepared = _prepared_request()

    with pytest.raises(ValidationError, match="created_at must be timezone-aware"):
        prepared.model_copy(
            update={"created_at": datetime(2026, 8, 1, 3, 0)},
        ).model_dump()
        PreparedRequest.model_validate(
            {
                **prepared.model_dump(),
                "created_at": datetime(2026, 8, 1, 3, 0),
            }
        )


def test_orchestration_package_exports_public_contract() -> None:
    from app.orchestration import CoreRequest as ExportedCoreRequest
    from app.orchestration import PreparedRequest as ExportedPreparedRequest

    assert ExportedCoreRequest is CoreRequest
    assert ExportedPreparedRequest is PreparedRequest
