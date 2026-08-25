from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest

from app.openclaw import OpenClawExecutionRequest, OpenClawExecutor
from app.orchestration.coding_governance import CodingAssignment


def _request() -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_1",
        run_id="run_1",
        attempt=1,
        idempotency_key="run_1:1",
        project_id="proj_1",
        goal="Perform a governed repair",
        mode="build",
        workspace="/mnt/f/AIOS/anh-duong-core",
        constraints=("Do not deploy",),
    )


@pytest.mark.asyncio
async def test_governed_request_binds_instructions_to_exact_workspace() -> None:
    captured: dict[str, Any] = {}
    workspace = "/workspaces/anh-duong-core.worktrees/ad-l5-05-reconstruct"
    assignment = CodingAssignment(
        checkpoint_id="AD-L5-05",
        correlation_id="corr_123",
        workspace=workspace,
        manifest_digest="a" * 64,
        allowed_paths=("app/openclaw/executor.py", "tests/unit/"),
        reviewer_required=True,
        approval_required=False,
        max_semantic_repair_rounds=2,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "outcome": "blocked",
                                        "summary": "Workspace inaccessible",
                                    }
                                ),
                            }
                        ]
                    }
                ]
            },
        )

    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(handler),
    )
    result = await executor.execute(
        _request().model_copy(update={"governed_coding": assignment})
    )

    outgoing_input = json.loads(cast(str, captured["input"]))
    instructions = cast(str, captured["instructions"])
    assert outgoing_input["workspace"] == workspace
    assert outgoing_input["governed_coding"]["workspace"] == workspace
    for required in (
        f"exact mapped workspace `{workspace}`",
        f"output must equal `{workspace}` exactly",
        "isolated git worktree",
        "Never fall back to $OPENCLAW_HOME",
        "/home/node/.openclaw/workspace",
        repr(assignment.allowed_paths),
        "return outcome `blocked`",
        "real commands/tests",
        "complete governance_result",
        "checkpoint_id='AD-L5-05'",
        "correlation_id='corr_123'",
        f"manifest_digest={'a' * 64!r}",
        "Do not write to production",
        "read-only reviewer outcome of PASS",
        "exactly `MERGE_READY`",
    ):
        assert required in instructions
    assert result.outcome == "blocked"
    assert result.governance_result is None


@pytest.mark.asyncio
async def test_ordinary_request_keeps_generic_instructions() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "outcome": "completed",
                                        "summary": "Done",
                                    }
                                ),
                            }
                        ]
                    }
                ]
            },
        )

    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(handler),
    )
    await executor.execute(_request())

    instructions = cast(str, captured["instructions"])
    assert "Execute the supplied task" in instructions
    assert "GOVERNED CODING REQUIREMENTS" not in instructions
