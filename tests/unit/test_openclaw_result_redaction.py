from __future__ import annotations

import json

import httpx
import pytest

from app.openclaw import OpenClawExecutionRequest, OpenClawExecutor


def _request() -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_redaction",
        run_id="run_redaction",
        attempt=1,
        idempotency_key="run_redaction:1",
        project_id="proj_1",
        goal="Return a final result safely",
        mode="build",
    )


@pytest.mark.asyncio
async def test_normalized_fallback_summary_redacts_sensitive_fields() -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuv"

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
                                        "api_key": secret,
                                        "artifacts": {"note": "done"},
                                    }
                                ),
                            }
                        ]
                    }
                ]
            },
        )

    result = await OpenClawExecutor(
        base_url="http://127.0.0.1:18789",
        transport=httpx.MockTransport(handler),
    ).execute(_request())

    assert result.outcome == "completed"
    assert secret not in result.summary
    assert "[REDACTED]" in result.summary
