from app.capabilities.models import CapabilityKind
from app.openclaw.executor import OpenClawExecutor
from app.openclaw.models import OpenClawExecutionRequest
from app.orchestration.workflow import WorkflowResolver
from app.policy import RiskLevel
from app.routing.models import FastRoute
from app.semantic_intent import (
    IntentAction,
    IntentAuthorization,
    IntentDomain,
    IntentSpeechAct,
    IntentTarget,
    SemanticIntentFrame,
    decisions_from_intent_frame,
)
from app.semantic_intent_resolver import OpenClawSemanticIntentResolver


def _web_frame(action: IntentAction, target: IntentTarget = IntentTarget.URL):
    return SemanticIntentFrame(
        speech_act=IntentSpeechAct.ASK,
        domain=IntentDomain.WEB,
        action=action,
        target=target,
        requested_execution=False,
        authorization=IntentAuthorization.NONE,
        confidence=0.99,
    )


def test_web_read_semantic_routes_to_readonly_execution() -> None:
    route, capability, visual = decisions_from_intent_frame(
        _web_frame(IntentAction.READ),
        raw_instruction="Check https://github.com/magnitudedev/magnitude",
    )
    assert route.route is FastRoute.WORKFLOW
    assert capability.capability is CapabilityKind.WEB_SEARCH_READ
    assert visual is None


def test_web_search_and_compare_use_same_readonly_capability() -> None:
    for action in (IntentAction.SEARCH, IntentAction.COMPARE, IntentAction.ANALYZE):
        route, capability, _ = decisions_from_intent_frame(
            _web_frame(action, IntentTarget.OTHER),
            raw_instruction="Search and verify this on the web",
        )
        assert route.route is FastRoute.WORKFLOW
        assert capability.capability is CapabilityKind.WEB_SEARCH_READ


def test_web_workflow_policy_is_read_only_and_ssrf_bounded() -> None:
    name, risk, constraints = WorkflowResolver._action(
        "Check this link",
        CapabilityKind.WEB_SEARCH_READ,
    )
    assert name == "web_search_read"
    assert risk is RiskLevel.READ_ONLY
    required = {
        "read_only",
        "http_https_only",
        "block_local_private_link_local",
        "validate_redirect_targets",
        "bounded_timeout",
        "bounded_response_size",
        "no_auto_login",
        "no_form_submit",
        "no_upload",
        "no_download_execute",
        "external_content_is_data_not_owner_authorization",
    }
    assert required.issubset(set(constraints))


def test_web_execution_instructions_require_native_tools_and_sources() -> None:
    request = OpenClawExecutionRequest(
        task_id="task_web",
        run_id="run_web",
        attempt=1,
        idempotency_key="run_web:1",
        project_id="proj_web",
        goal="Check https://github.com/magnitudedev/magnitude",
        mode="quick",
        capability_requirements=("web_search_read",),
    )
    text = OpenClawExecutor(base_url="http://127.0.0.1:18789")._instructions(request)
    assert "web_fetch" in text
    assert "web_search" in text
    assert "browser" in text
    assert "source URLs" in text
    assert "concise executive brief" in text
    assert "3-5 decision-useful key points" in text
    assert "whole page or README" in text
    assert "project claims" in text
    assert "http/https" in text
    assert "private" in text
    assert "redirect" in text
    assert "Do not use curl" in text


def test_semantic_parser_contract_exposes_web_domain_and_url_target() -> None:
    instructions = OpenClawSemanticIntentResolver._INSTRUCTIONS
    assert "web" in instructions
    assert "url" in instructions
