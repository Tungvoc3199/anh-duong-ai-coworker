import json

import httpx
import pytest

from app.openclaw import OpenClawExecutionRequest, OpenClawExecutor


def request():
    return OpenClawExecutionRequest(
        task_id="task_contract",
        run_id="run_contract",
        attempt=1,
        idempotency_key="run_contract:1",
        project_id="proj_1",
        goal="Check Core and OpenClaw",
        mode="quick",
        workspace="/home/thadc/AIOS/anh-duong-core",
        dod_criteria=("Core and OpenClaw status verified",),
    )


@pytest.mark.parametrize(
    "host,target",
    [
        ("/home/thadc/AIOS/anh-duong-core", "/workspaces/anh-duong-core"),
        ("/home/thadc/AIOS/anh-duong-core/app", "/workspaces/anh-duong-core/app"),
        ("/mnt/f/AIOS/anh-duong-core", "/workspaces/anh-duong-core"),
        ("/home/thadc/AIOS/anh-duong-core-other", "/home/thadc/AIOS/anh-duong-core-other"),
    ],
)
def test_workspace_namespace(host, target):
    assert OpenClawExecutor._gateway_workspace(host) == target


@pytest.mark.asyncio
async def test_fenced_structured_result_preserves_criterion_evidence():
    payload = {
        "outcome": "completed",
        "summary": "Checked both endpoints",
        "criterion_verification": [
            {
                "criterion": request().dod_criteria[0],
                "status": "verified",
                "evidence_refs": ["Core /ready HTTP 200; Gateway /health HTTP 200"],
            }
        ],
    }

    def handler(req):
        return httpx.Response(
            200,
            json={
                "id": "resp_contract",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": "```json\n" + json.dumps(payload) + "\n```",
                            }
                        ]
                    }
                ],
            },
        )

    result = await OpenClawExecutor(
        base_url="http://gateway", transport=httpx.MockTransport(handler)
    ).execute(request())
    assert len(result.criterion_verification) == 1
    assert result.summary == "Checked both endpoints"
    assert result.external_run_id == "resp_contract"


def test_dod_request_requires_json_and_explicit_runtime_scope():
    text = OpenClawExecutor(base_url="http://gateway")._instructions(request())
    assert "Return exactly one JSON object" in text
    assert "ANH_DUONG_CORE_BASE_URL" in text
    assert "container-local" in text
    assert "Do not send Telegram messages" in text


def test_image_subscription_route_instruction_attests_pinned_9router_codex_route():
    image_request = OpenClawExecutionRequest(
        task_id="task_image_route",
        run_id="run_image_route",
        attempt=1,
        idempotency_key="run_image_route:1",
        project_id="proj_1",
        goal="Sửa ảnh theo lỗi vừa nêu",
        mode="quick",
        workspace="/home/thadc/AIOS/anh-duong-core",
        constraints=("subscription_quota_only", "no_paid_fallback"),
    )
    text = OpenClawExecutor(base_url="http://gateway")._instructions(image_request)
    assert "openai/cx/gpt-5.5-image" in text
    assert "local 9Router transport" in text
    assert "explicit 'cx/' model prefix" in text
    assert "must not trigger the paid-route block" in text
    assert "Do not substitute another model/provider" in text
