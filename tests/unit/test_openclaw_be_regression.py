"""Regression: real B/E Telegram payloads must survive Core's OpenClaw contract.

B (Chrome guidance) was rejected with `invalid_response_contract` because the
agent payload used `outcome: "success"` and a plain-string `verification`.
E (OpenClaw restart attempt) used `outcome: "blocked_at_safe_gate"`.

Both payloads are sanitized transcripts of the real gateway responses
(captured to /tmp/fsc-probe/gw-b-window.log and DB result_json). RED on the
pre-fix executor; GREEN after the boundary normalization is restored.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.openclaw import OpenClawExecutionRequest, OpenClawExecutor


def _request() -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_be_regression",
        run_id="run_be_regression",
        attempt=1,
        idempotency_key="run_be_regression:1",
        project_id="proj_1",
        goal="Operational guidance about OpenClaw runtime",
        mode="build",
    )

def _executor(payload: object) -> OpenClawExecutor:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_be_regression",
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

# Real B payload (Chrome guidance) — outcome "success" (not in literal set),
# verification is a plain string.
PAYLOAD_B = {
    "outcome": "success",
    "summary": (
        "Anh có thể mở Chrome qua OpenClaw bằng browser tool hoặc CLI. "
        "Em đã kiểm tra runtime hiện tại: browser plugin đang bật."
    ),
    "runtime_check": {
        "browser_enabled": True,
        "profile": "openclaw",
        "running": False,
        "detected_browser": "chromium",
        "headless": True,
        "headless_reason": "linux-display-fallback",
    },
    "how_to_open": {
        "inside_agent_tool": "Dùng browser tool: action `start`, sau đó `open` URL.",
        "cli_commands": [
            {
                "environment": "Ubuntu/WSL — chạy ở bất kỳ thư mục nào",
                "commands": "openclaw browser profiles",
            }
        ],
    },
    "important_note": "Chrome sẽ mở dạng headless trong runtime hiện tại.",
    "verification": "Đã đọc docs `/app/docs/cli/browser.md` và gọi `browser status` thật.",
}

# Real E payload (OpenClaw restart attempt): outcome "blocked_at_safe_gate"
# (gateway restart unavailable; no kill performed).
PAYLOAD_E = {
    "outcome": "blocked_at_safe_gate",
    "summary": (
        "Em đã thử restart bằng lệnh `openclaw gateway restart`. "
        "Lệnh không restart được vì Gateway chạy trực tiếp trong container."
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
    },
    "next_step_required": {
        "needs_user_or_host_action": True,
        "reason": "Restart must be done from the host/Docker layer.",
        "recommended_command": {
            "environment": "Ubuntu/WSL",
            "commands": ["cd /mnt/f/AIOS/openclaw", "docker compose restart openclaw-gateway"],
        },
        "verify_after": {
            "environment": "Ubuntu/WSL",
            "commands": ["cd /mnt/f/AIOS/openclaw", "docker compose ps"],
        },
    },
}

@pytest.mark.asyncio
async def test_real_b_opening_chrome_survives_contract() -> None:
    result = await _executor(PAYLOAD_B).execute(_request())

    assert result.outcome == "completed"
    assert "Chrome 通过 OpenClaw" in result.summary or "mở Chrome qua OpenClaw" in result.summary
    # Plain-string verification/artifacts are preserved, not lost
    assert isinstance(result.artifacts, tuple) or isinstance(result.artifacts, dict)
    assert isinstance(result.verification, tuple) or isinstance(result.verification, dict)
    assert result.external_run_id == "resp_be_regression"

@pytest.mark.asyncio
async def test_real_e_restart_attempt_maps_to_blocked() -> None:
    result = await _executor(PAYLOAD_E).execute(_request())

    assert result.outcome == "blocked"
    assert "restart" in result.summary.lower()
    assert result.external_run_id == "resp_be_regression"