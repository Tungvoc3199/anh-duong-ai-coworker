from __future__ import annotations

import json

import httpx
import pytest

from app.openclaw import OpenClawExecutionRequest, OpenClawExecutor


def _request() -> OpenClawExecutionRequest:
    return OpenClawExecutionRequest(
        task_id="task_variants",
        run_id="run_variants",
        attempt=1,
        idempotency_key="run_variants:1",
        project_id="proj_1",
        goal="Return a final answer despite metadata variation",
        mode="build",
    )


def _executor(payload: object) -> OpenClawExecutor:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_variants",
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "outcome", "summary"),
    (
        ({"status": "succeeded", "message": "Hoàn tất."}, "completed", "Hoàn tất."),
        (
            {"state": "approval-required", "answer": "Cần anh duyệt bước gửi."},
            "blocked",
            "Cần anh duyệt bước gửi.",
        ),
        ({"status": "failure", "answer": "Không thể hoàn tất."}, "failed", "Không thể hoàn tất."),
        (
            {
                "final_answer": "Đã xử lý xong.",
                "artifacts": 37,
                "verification": False,
            },
            "completed",
            "Đã xử lý xong.",
        ),
        (
            {
                "outcome": "completed",
                "summary": "Có kết quả.",
                "artifacts": [{"kind": "report"}],
                "verification": [1, 2],
            },
            "completed",
            "Có kết quả.",
        ),
        (
            {"result": {"status": "ok", "response": "Kết quả lồng nhau."}},
            "completed",
            "Kết quả lồng nhau.",
        ),
        (
            {"outcome": "provider_custom_state", "text": "Vẫn có final."},
            "failed",
            "Vẫn có final.",
        ),
    ),
)
async def test_agent_final_survives_metadata_variants(
    payload: object,
    outcome: str,
    summary: str,
) -> None:
    result = await _executor(payload).execute(_request())

    assert result.outcome == outcome
    assert result.summary == summary
    assert result.external_run_id == "resp_variants"


@pytest.mark.asyncio
async def test_noncritical_metadata_is_coerced_without_losing_final() -> None:
    result = await _executor(
        {
            "outcome": "done",
            "summary": "Final vẫn còn.",
            "files_changed": 7,
            "commands_run": None,
            "tests": True,
            "duration_ms": -1,
        }
    ).execute(_request())

    assert result.outcome == "completed"
    assert result.summary == "Final vẫn còn."
    assert result.files_changed == ("7",)
    assert result.commands_run == ()
    assert result.tests == ({"result": "True"},)
    assert result.duration_ms is None
