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


def _request() -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_1",
        run_id="run_1",
        attempt=1,
        idempotency_key="run_1:1",
        project_id="proj_1",
        goal="Return a structured result",
        mode="build",
        workspace="/mnt/f/AIOS/anh-duong-core",
        constraints=("Do not deploy",),
    )

def _json_transport(
    payload: object,
    *,
    response_id: str = "resp_1",
) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": response_id,
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(payload, ensure_ascii=False),
                            }
                        ],
                    }
                ],
            },
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_executor_posts_openresponses_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get(
            "authorization"
        )
        captured["idempotency"] = request.headers.get(
            "idempotency-key"
        )
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "outcome": "completed",
                                        "summary": "Done",
                                        "artifacts": ["artifact.zip"],
                                        "verification": [
                                            "pytest passed"
                                        ],
                                        "files_changed": ["calculate.py"],
                                        "commands_run": ["pytest -q"],
                                        "tests": [
                                            {
                                                "name": "pytest",
                                                "status": "PASS",
                                            }
                                        ],
                                        "model": "cx/gpt-5.5",
                                        "provider": "router9",
                                        "profile": "CE-2",
                                        "duration_ms": 1234,
                                        "error_code": None,
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        execution_path="/v1/responses",
        auth_token="test-token",
        timeout_seconds=600,
        transport=httpx.MockTransport(handler),
    )

    result = await executor.execute(_request())

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/responses"
    assert captured["authorization"] == "Bearer test-token"
    assert captured["idempotency"] == "run_1:1"
    assert isinstance(captured["json"], dict)
    assert captured["json"]["model"] == "openclaw/default"
    request_payload = json.loads(cast(dict[str, Any], captured["json"])["input"])
    assert request_payload["workspace"] == "/workspaces/anh-duong-core"

    assert result.outcome == "completed"
    assert result.summary == "Done"
    assert result.external_run_id == "resp_1"
    assert result.files_changed == ("calculate.py",)
    assert result.commands_run == ("pytest -q",)
    assert result.tests == (
        {
            "name": "pytest",
            "status": "PASS",
        },
    )
    assert result.model == "cx/gpt-5.5"
    assert result.provider == "router9"
    assert result.profile == "CE-2"
    assert result.duration_ms == 1234
    assert result.error_code is None


@pytest.mark.asyncio
async def test_executor_accepts_real_workflow_result_objects() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_real_workflow",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "outcome": "success",
                                        "summary": (
                                            "Đã soạn checklist 5 bước kiểm tra "
                                            "trạng thái Ánh Dương Core theo chế "
                                            "độ chỉ đọc, không chạy lệnh, không "
                                            "sửa file, không sửa cấu hình và "
                                            "không restart dịch vụ."
                                        ),
                                        "artifacts": {
                                            "checklist": [
                                                {
                                                    "step": 1,
                                                    "name": (
                                                        "Xác nhận phạm vi kiểm tra"
                                                    ),
                                                    "check": (
                                                        "Đảm bảo phiên kiểm tra "
                                                        "chỉ nhằm quan sát trạng "
                                                        "thái Ánh Dương Core, "
                                                        "không thực hiện thao tác "
                                                        "thay đổi hệ thống."
                                                    ),
                                                    "readonly_rule": (
                                                        "Không chạy lệnh, không "
                                                        "gọi script, không chỉnh "
                                                        "file, không restart "
                                                        "service."
                                                    ),
                                                }
                                            ]
                                        },
                                        "verification": {
                                            "method": "static_review_only",
                                            "commands_run": 0,
                                            "files_changed": 0,
                                            "config_changed": False,
                                            "services_restarted": False,
                                            "notes": (
                                                "Không chạy lệnh, không đọc/sửa "
                                                "file và không kiểm tra trạng thái "
                                                "hệ thống thật do task yêu cầu "
                                                "read_only + no_commands."
                                            ),
                                        },
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        execution_path="/v1/responses",
        timeout_seconds=600,
        transport=httpx.MockTransport(handler),
    )

    result = await executor.execute(_request())

    assert result.outcome == "completed"
    assert result.external_run_id == "resp_real_workflow"
    assert result.artifacts.checklist[0].step == 1
    assert result.artifacts.checklist[0].name == "Xác nhận phạm vi kiểm tra"
    assert result.verification.method == "static_review_only"
    assert result.verification.commands_run == 0
    assert result.verification.services_restarted is False


@pytest.mark.asyncio
async def test_executor_accepts_readonly_health_ready_result_objects() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_readonly_health_ready",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "outcome": "completed",
                                        "summary": (
                                            "Đã kiểm tra read-only hai endpoint "
                                            "/health và /ready."
                                        ),
                                        "artifacts": {
                                            "checked_endpoints": [
                                                "http://localhost:8000/health",
                                                "http://localhost:8000/ready",
                                            ],
                                            "changes_made": "none",
                                            "restarts": "none",
                                            "config_changes": "none",
                                            "file_changes": "none",
                                        },
                                        "verification": {
                                            "health": {
                                                "status": "ok",
                                                "http_status": 200,
                                            },
                                            "ready": {
                                                "status": "ready",
                                                "http_status": 200,
                                            },
                                        },
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        execution_path="/v1/responses",
        timeout_seconds=600,
        transport=httpx.MockTransport(handler),
    )

    result = await executor.execute(_request())

    assert result.outcome == "completed"
    assert result.external_run_id == "resp_readonly_health_ready"
    assert result.artifacts["changes_made"] == "none"
    assert result.verification["health"]["status"] == "ok"

@pytest.mark.asyncio
async def test_executor_preserves_final_when_known_artifacts_are_partial() -> None:
    payload = {
        "outcome": "success",
        "summary": "Đã làm xong và đây là báo cáo.",
        "artifacts": {
            "checklist": [
                {
                    "step": 1,
                    "name": "Partial item from agent",
                }
            ]
        },
        "verification": {
            "method": "static_review_only",
            "commands_run": 0,
            "files_changed": 0,
            "config_changed": False,
            "services_restarted": False,
            "notes": "No commands were run.",
        },
    }
    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        transport=_json_transport(payload),
    )

    result = await executor.execute(_request())

    assert result.outcome == "completed"
    assert result.summary == "Đã làm xong và đây là báo cáo."
    assert isinstance(result.artifacts, dict)
    assert result.artifacts["checklist"][0]["name"] == "Partial item from agent"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "retryable", "code"),
    (
        (408, True, "gateway_timeout"),
        (429, True, "rate_limited"),
        (502, True, "gateway_unavailable"),
        (503, True, "gateway_unavailable"),
        (504, True, "gateway_timeout"),
        (401, False, "authentication_error"),
        (403, False, "authentication_error"),
        (400, False, "contract_error"),
        (404, False, "contract_error"),
        (422, False, "contract_error"),
    ),
)
async def test_executor_classifies_http_errors(
    status_code: int,
    retryable: bool,
    code: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": "request failed"}},
        )

    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        execution_path="/v1/responses",
        timeout_seconds=600,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(OpenClawTransportError) as captured:
        await executor.execute(_request())

    assert captured.value.retryable is retryable
    assert captured.value.code == code


@pytest.mark.asyncio
async def test_executor_timeout_is_uncertain_and_never_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response lost", request=request)

    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        execution_path="/v1/responses",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(OpenClawTransportError) as captured:
        await executor.execute(_request())

    assert captured.value.code == "timeout"
    assert captured.value.retryable is False
    assert captured.value.uncertain_side_effect is True


@pytest.mark.asyncio
async def test_executor_normalizes_success_outcome_to_completed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
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
                                        "outcome": "success",
                                        "summary": "Done",
                                        "artifacts": [],
                                        "verification": [],
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

    result = await executor.execute(_request())

    assert result.outcome == "completed"


@pytest.mark.asyncio
async def test_executor_answer_only_json_becomes_completed_final_reply() -> None:
    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        transport=_json_transport({"answer": "Em đã sửa xong, kiểm tra PASS."}),
    )

    result = await executor.execute(_request())

    assert result.outcome == "completed"
    assert result.summary == "Em đã sửa xong, kiểm tra PASS."


@pytest.mark.asyncio
async def test_executor_plain_exec_failed_is_never_completed() -> None:
    terminal_text = (
        "⚠️ 🛠️ Exec failed: `check git status -> show first 30 lines "
        "→ run git worktree (in /home/thadc/AIOS/anh-duong-core)`"
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_exec_failed",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": terminal_text,
                            }
                        ]
                    }
                ],
            },
        )

    executor = OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(handler),
    )
    result = await executor.execute(_request())

    assert result.outcome == "failed"
    assert result.error_code == "openclaw_exec_failed"
    assert result.summary == terminal_text
    assert result.external_run_id == "resp_exec_failed"
