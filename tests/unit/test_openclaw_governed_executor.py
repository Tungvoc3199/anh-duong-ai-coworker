"""RED tests: governed executor mapping and typed result parsing (AD-L5-05).

The OpenClaw executor must carry the typed coding assignment into the gateway
request, must never map a non-worktree workspace onto the production gateway
workspace, and must parse a typed ``governance_result`` from the response.
"""
from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest

from app.openclaw import (
    OpenClawExecutionRequest,
    OpenClawExecutor,
    OpenClawTransportError,
)
from app.orchestration.coding_governance import (
    CodingAssignment,
    CodingResultContract,
    FailureClassification,
    ReviewerOutcome,
)


def _assignment() -> CodingAssignment:
    return CodingAssignment(
        checkpoint_id="AD-L5-05",
        correlation_id="req_exec_1",
        workspace="/home/thadc/AIOS/anh-duong-core.worktrees/exec-1",
        manifest_digest="b" * 64,
        allowed_paths=("app/", "tests/"),
        reviewer_required=True,
        approval_required=False,
        max_semantic_repair_rounds=2,
    )


def _governed_request(
    *,
    workspace: str | None = None,
) -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_gov",
        run_id="run_gov",
        attempt=1,
        idempotency_key="run_gov:1",
        project_id="proj_gov",
        goal="Implement governed change.",
        mode="build",
        workspace=workspace,
        constraints=("no_deploy",),
        governed_coding=_assignment(),
    )


def _json_transport(payload: object) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_gov",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    payload, ensure_ascii=False
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    return httpx.MockTransport(handler)


def _executor(transport: httpx.MockTransport) -> OpenClawExecutor:
    return OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        execution_path="/v1/responses",
        auth_token="test-token",
        timeout_seconds=600,
        transport=transport,
    )


def _merge_ready_payload() -> dict[str, Any]:
    return {
        "outcome": "completed",
        "summary": "Merge-ready coding result.",
        "files_changed": ["app/example.py"],
        "commands_run": ["pytest -q"],
        "tests": [{"name": "pytest", "status": "PASS"}],
        "model": "router/model",
        "provider": "router",
        "profile": "CE-2",
        "duration_ms": 100,
        "error_code": None,
        "governance_result": {
            "checkpoint_id": "AD-L5-05",
            "correlation_id": "req_exec_1",
            "status": "MERGE_READY",
            "classification": FailureClassification.DELTA_FAILURE.value,
            "manifest_digest": "b" * 64,
            "files_changed": ["app/example.py"],
            "commands_run": ["pytest -q"],
            "tests": [{"name": "pytest", "status": "PASS"}],
            "model": "router/model",
            "provider": "router",
            "profile": "CE-2",
            "duration_ms": 100,
            "error_code": None,
            "production_write": False,
            "service_restart": False,
            "database_write": False,
            "reviewer_outcome": ReviewerOutcome.PASS.value,
            "reviewer_read_only": True,
            "approval_granted": False,
            "repair_round": 0,
        },
    }


@pytest.mark.asyncio
async def test_executor_carries_assignment_into_gateway_input() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["input"] = json.loads(body["input"])
        return httpx.Response(
            200,
            json={
                "id": "resp_carry",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "outcome": "completed",
                                        "summary": "Done.",
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    executor = _executor(httpx.MockTransport(handler))
    await executor.execute(_governed_request())

    request_payload = cast(dict[str, Any], captured["input"])
    assert request_payload["governed_coding"]["checkpoint_id"] == "AD-L5-05"
    assert (
        request_payload["governed_coding"]["manifest_digest"] == "b" * 64
    )


@pytest.mark.asyncio
async def test_executor_refuses_production_workspace_mapping() -> None:
    with pytest.raises(OpenClawTransportError):
        await _executor(_json_transport({"outcome": "failed"})).execute(
            _governed_request(
                workspace="/home/thadc/AIOS/anh-duong-core"
            )
        )


@pytest.mark.asyncio
async def test_executor_does_not_map_unrelated_worktree_to_production() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["input"] = json.loads(body["input"])
        return httpx.Response(
            200,
            json={
                "id": "resp_map",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "outcome": "completed",
                                        "summary": "Done.",
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    executor = _executor(httpx.MockTransport(handler))
    await executor.execute(
        _governed_request(
            workspace=(
                "/home/thadc/AIOS/anh-duong-core.worktrees/exec-1"
            )
        )
    )

    request_payload = cast(dict[str, Any], captured["input"])
    assert request_payload["workspace"] != "/workspaces/anh-duong-core"
    assert request_payload["workspace"] == (
        "/home/thadc/AIOS/anh-duong-core.worktrees/exec-1"
    )


@pytest.mark.asyncio
async def test_executor_parses_typed_governance_result() -> None:
    result = await _executor(
        _json_transport(_merge_ready_payload())
    ).execute(_governed_request())

    assert result.outcome == "completed"
    governance = result.governance_result
    assert isinstance(governance, CodingResultContract)
    assert governance.status == "MERGE_READY"
    assert governance.reviewer_outcome is ReviewerOutcome.PASS
    assert governance.reviewer_read_only is True


@pytest.mark.asyncio
async def test_executor_leaves_plain_results_without_governance() -> None:
    result = await _executor(
        _json_transport(
            {"outcome": "completed", "summary": "Plain workflow."}
        )
    ).execute(
        OpenClawExecutionRequest(
            task_id="task_plain",
            run_id="run_plain",
            attempt=1,
            idempotency_key="run_plain:1",
            project_id="proj_plain",
            goal="Ordinary workflow.",
            mode="quick",
        )
    )

    assert result.outcome == "completed"
    assert result.governance_result is None
