from __future__ import annotations

import json
from typing import Any

import pytest

from app.async_tasks import AsyncRunStatus, AsyncTaskRepository
from app.planning.repository import PlanRepository
from app.tasks import TaskRepository, TaskService, TaskStatus
from app.visualforge import VisualForgeCompiledPrompt, VisualForgeRoutingExecutor
from tests.integration.test_async_task_worker import NOW, _audit, _seed_run, _worker
from tests.integration.test_async_task_worker import engine as engine
from tests.integration.test_async_task_worker import session_factory as session_factory


class RejectingDelegate:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def execute(self, request: Any) -> Any:
        self.requests.append(request)
        raise AssertionError("VisualForge workflow must not call OpenClaw")


class LocalVisualForgeClient:
    def __init__(self) -> None:
        self.specs: list[Any] = []

    async def compose(self, spec: Any) -> VisualForgeCompiledPrompt:
        self.specs.append(spec)
        return VisualForgeCompiledPrompt(
            prompt=f"LOCAL PROMPT\nExact text: {spec.required_text}",
            adapter="gpt-image",            required_text=spec.required_text,
            provenance_notes=("dna-local; source=pinned; license=CC-BY-4.0",),
            sections={"task_subject": "local visual prompt"},
        )


@pytest.mark.asyncio
async def test_visualforge_planned_run_completes_with_local_durable_evidence(
    session_factory,
    tmp_path,
) -> None:
    goal = (
        'Dùng VisualForge tạo prompt ảnh TikTok serum 9:16, '
        'text chính xác "GIẢM 50% HÔM NAY"'
    )
    task_id, run_id = _seed_run(
        session_factory,
        tmp_path,
        key="visualforge-planned",
        goal=goal,
    )
    delegate = RejectingDelegate()
    client = LocalVisualForgeClient()
    executor = VisualForgeRoutingExecutor(delegate=delegate, client=client)
    worker = _worker(
        session_factory=session_factory,
        tmp_path=tmp_path,
        executor=executor,
        clock=[NOW],
    )
    assert await worker.run_once() is True

    with session_factory() as session:
        run = AsyncTaskRepository(session).get(run_id)
        task = TaskService(TaskRepository(session), _audit(tmp_path)).get(task_id)
        plan = PlanRepository(session).get(run_id)

    assert run.status is AsyncRunStatus.COMPLETED
    assert task.status is TaskStatus.COMPLETED
    assert delegate.requests == []
    assert len(client.specs) == 1
    assert plan is not None
    states = {item.node_id: item.state.value for item in plan.node_executions}
    assert states == {"execute": "completed", "verify": "completed"}
    assert plan.outcome_judgement is not None
    assert plan.outcome_judgement["disposition"] == "satisfied"
    assert [item.provenance for item in plan.evidence] == ["visualforge"]
    payload = json.loads(run.result_json or "{}")
    assert payload["profile"] == "visualforge-v0.2"
    assert payload["external_run_id"] is None
    assert payload["commands_run"] == []
    assert payload["files_changed"] == []
    assert payload["artifacts"]["required_text"] == "GIẢM 50% HÔM NAY"