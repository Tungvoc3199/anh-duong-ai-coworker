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
