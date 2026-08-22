"""Regression: operational responses must not quote stale runtime facts.

Replays the real E Telegram request chain ("Restart OpenClaw"): the OpenClaw
gateway response (resp_559ce3bc-c5c5-4ffd-b0b0-a396898166a4) recommended
``cd /mnt/f/AIOS/openclaw`` + ``docker compose restart openclaw-gateway``.
That path is hardcoded in OpenClaw's historical instruction files
(AGENTS.md/TOOLS.md/USER.md/SOUL.md), but ``/mnt/f/AIOS/openclaw`` does not
exist in the current runtime (real compose project:
``/home/thadc/AIOS/openclaw``). Core must never forward a host path/command
that was not verified within the current request; it must reply UNKNOWN
instead of fabricating commands/paths.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.openclaw import OpenClawExecutionRequest, OpenClawExecutor


def _request() -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_evidence_e",
        run_id="run_evidence_e",
        attempt=1,
        idempotency_key="run_evidence_e:1",
        project_id="proj_1",
        goal="Restart OpenClaw",
        mode="quick",
        workspace="/mnt/f/AIOS/anh-duong-core",
    )


def _executor(payload: object) -> OpenClawExecutor:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_evidence_e",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(payload, ensure_ascii=False),
                            }
                        ]
                    }
                ],
            },
        )

    return OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(handler),
    )


# The exact stale command OpenClaw sent in the real E window:
# the path came from historical instructions, not from fresh runtime evidence.
PAYLOAD_E_STALE = {
    "outcome": "blocked_at_safe_gate",
    "summary": (
        "Không thể restart từ phiên này vì Gateway không được quản lý bởi "
        "systemd (Gateway service disabled).\n"
        "Lệnh restart cần chạy ở môi trường quản lý Gateway/Docker:\n"
        "\n"
        "**Ubuntu/WSL — trong thư mục dự án OpenClaw**\n"
        "```bash\n"
        "cd /mnt/f/AIOS/openclaw\n"
        "docker compose restart openclaw-gateway\n"
        "docker compose ps\n"
        "```"
    ),
    "artifacts": {
        "workspace_checked": "/workspaces/anh-duong-core",
        "restart_command_attempted": "openclaw gateway restart",
        "restart_result": "Gateway service disabled.",
        "health_check": "Gateway Health OK",
    },
    "verification": {
        "commands_run": ["openclaw status", "openclaw gateway restart"],
        "current_state": "Gateway is still running and healthy.",
        "restart_command_attempted": (
            "cd /mnt/f/AIOS/openclaw && docker compose restart openclaw-gateway"
        ),
    },
}


@pytest.mark.asyncio
async def test_e_stale_path_replaced_with_unknown() -> None:
    """E must not leak the unverified /mnt/f/AIOS/openclaw path."""
    result = await _executor(PAYLOAD_E_STALE).execute(_request())

    assert result.outcome == "blocked"
    summary = result.summary
    # The stale path must be gone; the guard must have replaced it.
    assert "/mnt/f/AIOS/openclaw" not in summary
    assert "UNKNOWN" in summary
    # No invented command block survives either.
    assert "docker compose restart" not in summary
    assert "docker compose ps" not in summary
    assert "Gateway" in summary

    # Operational detail fields (verification/artifacts reach the Telegram
    # notification) must be guarded too: stale anchors go, fresh paths stay.
    assert result.verification["commands_run"] == [
        "openclaw status",
        "openclaw gateway restart",
    ]
    assert result.verification["current_state"] == (
        "Gateway is still running and healthy."
    )
    assert "UNKNOWN" in str(result.verification["restart_command_attempted"])
    assert "/mnt/f/AIOS/openclaw" not in str(result.verification)
    assert result.artifacts["workspace_checked"] == "/workspaces/anh-duong-core"


@pytest.mark.asyncio
async def test_runtime_evidence_policy_in_instructions() -> None:
    """The policy must be part of every request instruction."""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_instr",
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": "{}"}
                        ]
                    }
                ],
            },
        )

    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(handler),
    )
    await executor.execute(_request())

    instructions = str(captured["json"]["instructions"])
    assert "Runtime evidence rule" in instructions
    assert "tool output gathered during this same request" in instructions
    assert "Never copy paths or commands" in instructions
    assert "historical" in instructions


@pytest.mark.asyncio
async def test_fresh_workspace_path_is_kept() -> None:
    """A path verified within the current request (workspace) is not wiped."""
    payload = {
        "outcome": "blocked_at_safe_gate",
        "summary": (
            "Gateway restart requires host access. "
            "Workspace checked: /workspaces/anh-duong-core."
        ),
    }
    result = await _executor(payload).execute(_request())

    assert result.outcome == "blocked"
    assert "/workspaces/anh-duong-core" in result.summary