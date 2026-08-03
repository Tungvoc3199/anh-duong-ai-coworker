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
