from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.openclaw import OpenClawExecutionRequest, OpenClawExecutor
from app.orchestration.coding_governance import CodingAssignment


def _governed_request() -> OpenClawExecutionRequest:
    assignment = CodingAssignment(
        checkpoint_id="AD-L5-05",
        correlation_id="corr-1",
        workspace="/home/thadc/AIOS/anh-duong-core.worktrees/ad-l5-05",
        allowed_paths=("tests/",),
        manifest_digest="a" * 64,
        approval_required=False,
        reviewer_required=True,
        max_semantic_repair_rounds=1,
    )
    return OpenClawExecutionRequest(
        task_id="task-1",
        run_id="run-1",
        attempt=1,
        idempotency_key="run-1:1",
        project_id="project-1",
        goal="Add one test",
        mode="quick",
        workspace="/home/thadc/AIOS/anh-duong-core",
        governed_coding=assignment,
    )


def _transport(text: str) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp-1",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": text}],
                    }
                ],
            },
        )

    return httpx.MockTransport(handler)


async def _execute(text: str) -> Any:
    executor = OpenClawExecutor(
        base_url="http://gateway.invalid",
        transport=_transport(text),
    )
    return await executor.execute(_governed_request())


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ("blocked", "failed"))
async def test_governed_blocked_or_failed_json_survives_diagnostic_suffix(
    outcome: str,
) -> None:
    payload = {
        "outcome": outcome,
        "summary": "Stopped at the governed safety gate.",
        "error_code": "isolated_worktree_invalid",
    }

    result = await _execute(
        json.dumps(payload) + "\n⚠️ 🛠️ Exec failed: git rev-parse exited 128"
    )

    assert result.outcome == outcome
    assert result.summary == payload["summary"]
    assert result.error_code == payload["error_code"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    (
        "not json",
        '["completed"]',
        '{"outcome":"completed","summary":"Done"}\ntrailing diagnostic',
    ),
)
async def test_malformed_governed_output_never_defaults_to_completed(
    text: str,
) -> None:
    result = await _execute(text)

    assert result.outcome == "failed"
    assert result.error_code == "invalid_response_contract"


@pytest.mark.asyncio
async def test_valid_governed_json_preserves_normal_result() -> None:
    result = await _execute(
        json.dumps({"outcome": "blocked", "summary": "Approval required"})
    )

    assert result.outcome == "blocked"
    assert result.summary == "Approval required"


@pytest.mark.asyncio
async def test_valid_complete_governance_result_can_complete() -> None:
    governance_result = {
        "checkpoint_id": "AD-L5-05",
        "correlation_id": "corr-1",
        "status": "MERGE_READY",
        "classification": "DELTA_FAILURE",
        "manifest_digest": "a" * 64,
        "files_changed": ["tests/test_add.py"],
        "commands_run": ["pytest -q tests/test_add.py"],
        "tests": [{"name": "pytest", "status": "PASS"}],
        "model": "test-model",
        "provider": "test-provider",
        "profile": "test-profile",
        "duration_ms": 10,
        "error_code": None,
        "production_write": False,
        "service_restart": False,
        "database_write": False,
        "reviewer_outcome": "PASS",
        "reviewer_read_only": True,
        "approval_granted": True,
        "repair_round": 1,
    }

    result = await _execute(
        json.dumps(
            {
                "outcome": "completed",
                "summary": "Governed change is merge ready.",
                "governance_result": governance_result,
            }
        )
    )

    assert result.outcome == "completed"
    assert result.governance_result is not None
    assert result.governance_result.status == "MERGE_READY"


def test_ordinary_plain_text_compatibility_is_preserved() -> None:
    payload = OpenClawExecutor._parse_result_payload("ordinary answer")

    assert payload["outcome"] == "completed"
    assert payload["summary"] == "ordinary answer"
