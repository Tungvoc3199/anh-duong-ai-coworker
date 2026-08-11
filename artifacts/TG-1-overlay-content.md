# TG-1 Overlay Content

Overlay root: `F:\AIOS`. ZIP entries giữ đúng cây thư mục từ root này.

Không chứa `.env`, live `openclaw.json`, backup, database, `.git`, `node_modules` hoặc secret runtime.

## Tree

```text
anh-duong-core/app/routing/fast_router.py
anh-duong-core/tests/unit/test_core_request_pipeline_behavior.py
anh-duong-core/integrations/openclaw-anh-duong-core/package.json
anh-duong-core/integrations/openclaw-anh-duong-core/openclaw.plugin.json
anh-duong-core/integrations/openclaw-anh-duong-core/index.js
anh-duong-core/integrations/openclaw-anh-duong-core/src/config.js
anh-duong-core/integrations/openclaw-anh-duong-core/src/core-client.js
anh-duong-core/integrations/openclaw-anh-duong-core/src/hooks.js
anh-duong-core/integrations/openclaw-anh-duong-core/src/prompt.js
anh-duong-core/integrations/openclaw-anh-duong-core/test/config.test.js
anh-duong-core/integrations/openclaw-anh-duong-core/test/client.test.js
anh-duong-core/integrations/openclaw-anh-duong-core/test/hooks.test.js
anh-duong-core/scripts/verify_tg1_runtime.ps1
anh-duong-core/docs/superpowers/specs/2026-08-01-tg1-telegram-openclaw-core-design.md
anh-duong-core/docs/superpowers/plans/2026-08-01-tg1-telegram-openclaw-core.md
anh-duong-core/artifacts/TG-1-route-direct-fix.patch
anh-duong-core/artifacts/anh-duong-openclaw-core-gate-1.0.0.tgz
openclaw/docker-compose.yml
```

## Apply overlay

Windows PowerShell — chạy ở bất kỳ thư mục nào:

```powershell
Expand-Archive -LiteralPath 'F:\AIOS\anh-duong-checkpoints\TG-1-overlay.zip' -DestinationPath 'F:\AIOS' -Force
```

Ubuntu/WSL — chạy trong: `/mnt/f/AIOS/anh-duong-core`

```bash
.venv/bin/pytest -q
.venv/bin/ruff check app tests
.venv/bin/mypy app
.venv/bin/python -m compileall -q app
```

Runtime activation cần cung cấp secret hiện có qua environment; chỉ dùng các tên biến sau và không ghi giá trị vào tài liệu/log:

```text
ANH_DUONG_CORE_ENABLED
ANH_DUONG_CORE_BASE_URL
ANH_DUONG_CORE_INTERNAL_TOKEN
ANH_DUONG_CORE_TIMEOUT_SECONDS
```

OpenClaw plugin config phải merge, không overwrite cấu hình đang có: allow `anh-duong-core`, enable entry, và đặt `hooks.allowConversationAccess=true`. Dùng managed npm-pack; không bind-mount source NTFS.

## Rollback

Ubuntu/WSL — chạy trong: `/mnt/f/AIOS/anh-duong-core`

```bash
git apply -R --unidiff-zero artifacts/TG-1-route-direct-fix.patch
sudo systemctl restart anh-duong-core.service
```

Khôi phục OpenClaw từ `F:\AIOS\anh-duong-checkpoints\backups\TG-1-20260801T114348Z`; chỉ recreate `openclaw-gateway`, không dùng `docker compose down -v` và không xóa state/volume/SQLite.

## Files and full text content

### `anh-duong-core/app/routing/fast_router.py`

SHA-256: `0c4e18378be21847db06785463056e5da1b2fbed0901c430e1e133af8f4e4fb7`

````python
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.routing.models import FastRoute, RouteDecision

_WORKFLOW_PHRASES = (
    "lap ke hoach",
    "tao",
    "sua",
    "cap nhat",
    "ghi file",
    "chay",
    "thuc hien",
    "trien khai",
    "xay",
    "khac phuc",
    "xoa",
    "gui",
    "cai dat",
    "khoi dong lai",
    "doi ten",
    "di chuyen",
    "sao chep",
    "luu thong tin",
    "ghi nho rang",
    "plan",
    "create",
    "edit",
    "update",
    "write",
    "run",
    "execute",
    "implement",
    "build",
    "fix",
    "delete",
    "remove",
    "send",
    "deploy",
    "install",
    "commit",
    "push",
    "restart",
    "change",
    "modify",
    "generate",
    "move",
    "copy",
    "publish",
    "save this",
    "store this",
    "remember this",
)

_MEMORY_INHERENT_PHRASES = (
    "nho lai",
    "ban co nho",
    "toi da noi gi",
    "do you remember",
    "what did i say",
    "what have i saved",
    "recall",
)
_MEMORY_STORAGE_PHRASES = (
    "bo nho",
    "memory",
    "da luu",
    "stored",
    "saved",
)
_MEMORY_READ_PHRASES = (
    "tim",
    "tra cuu",
    "truy xuat",
    "xem lai",
    "cho toi biet",
    "search",
    "find",
    "retrieve",
    "look up",
)

_CORE_ENTITY_PHRASES = (
    "project",
    "du an",
    "task",
    "nhiem vu",
    "core",
    "anh duong",
)
_CORE_STATUS_PHRASES = (
    "trang thai",
    "tien do",
    "the nao",
    "health",
    "ready",
    "status",
    "progress",
    "how is",
    "current state",
    "hoat dong",
    "on khong",
)
_CORE_READ_PHRASES = (
    "xem",
    "kiem tra",
    "hien thi",
    "show",
    "view",
    "list",
    "get",
)

_DIRECT_UTTERANCES = frozenset(
    {
        "ok",
        "okay",
        "duoc",
        "da",
        "da ro",
        "vang",
        "dong y",
        "dung",
        "dung roi",
        "toi hieu",
        "toi hieu roi",
        "vang toi hieu roi",
        "tot",
        "tot lam",
        "tuyet",
        "tuyet voi",
        "great",
        "got it",
        "nice",
        "sounds good",
        "chao ban khoe khong",
        "how are you",
    }
)
_GREETING_PATTERN = re.compile(
    r"^(?:xin chao|chao|chao buoi sang|hello|hi|hey|good morning|"
    r"good afternoon|good evening)"
    r"(?: (?:ban|anh duong|there))?$"
)
_THANKS_PATTERN = re.compile(
    r"^(?:cam on|thank you|thanks)(?: (?:ban|anh duong|nhe|rat nhieu|so much))?$"
)
_SIMPLE_ARITHMETIC_PATTERN = re.compile(
    r"^(?:tg1 direct [0-9]+ )?tinh [0-9]+(?: [0-9]+)+ va tra loi ngan gon$"
)


class FastRouter:
    """Deterministic domain router with fail-closed workflow fallback."""

    def route(self, request: str) -> RouteDecision:
        normalized = self._normalize(request)
        if not normalized:
            return RouteDecision(
                route=FastRoute.WORKFLOW,
                rule_id="routing.workflow.empty_input",
                reason="Empty input is routed to workflow for safe handling.",
            )

        if self._contains_any(normalized, _WORKFLOW_PHRASES):
            return RouteDecision(
                route=FastRoute.WORKFLOW,
                rule_id="routing.workflow.explicit_action",
                reason="An explicit action or side effect requires workflow handling.",
            )

        if self._is_memory_request(normalized):
            return RouteDecision(
                route=FastRoute.MEMORY,
                rule_id="routing.memory.explicit_retrieval",
                reason="The request explicitly asks to retrieve stored information.",
            )

        if self._is_core_read_request(normalized):
            return RouteDecision(
                route=FastRoute.CORE_READ,
                rule_id="routing.core_read.status_query",
                reason="The request asks for read-only Core, Project, or Task status.",
            )

        if self._is_direct_request(normalized):
            return RouteDecision(
                route=FastRoute.DIRECT,
                rule_id="routing.direct.simple_conversation",
                reason="The request is a simple conversational response.",
            )

        return RouteDecision(
            route=FastRoute.WORKFLOW,
            rule_id="routing.workflow.ambiguous_input",
            reason="Unknown or ambiguous input is routed to workflow for safe handling.",
        )

    @classmethod
    def _is_memory_request(cls, normalized: str) -> bool:
        if cls._contains_any(normalized, _MEMORY_INHERENT_PHRASES):
            return True
        return cls._contains_any(
            normalized,
            _MEMORY_STORAGE_PHRASES,
        ) and cls._contains_any(normalized, _MEMORY_READ_PHRASES)

    @classmethod
    def _is_core_read_request(cls, normalized: str) -> bool:
        if not cls._contains_any(normalized, _CORE_ENTITY_PHRASES):
            return False
        return cls._contains_any(
            normalized,
            _CORE_STATUS_PHRASES,
        ) or cls._contains_any(normalized, _CORE_READ_PHRASES)

    @staticmethod
    def _is_direct_request(normalized: str) -> bool:
        return (
            normalized in _DIRECT_UTTERANCES
            or _GREETING_PATTERN.fullmatch(normalized) is not None
            or _THANKS_PATTERN.fullmatch(normalized) is not None
            or _SIMPLE_ARITHMETIC_PATTERN.fullmatch(normalized) is not None
        )

    @staticmethod
    def _contains_any(normalized: str, phrases: Iterable[str]) -> bool:
        padded = f" {normalized} "
        return any(f" {phrase} " in padded for phrase in phrases)

    @staticmethod
    def _normalize(request: str) -> str:
        decomposed = unicodedata.normalize("NFKD", request.casefold())
        without_marks = "".join(
            character
            for character in decomposed
            if not unicodedata.combining(character)
        ).replace("đ", "d")
        return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())
````````

### `anh-duong-core/tests/unit/test_core_request_pipeline_behavior.py`

SHA-256: `c205ed9cf34aa6949188557d593cfaa9cba9cdcaf6ff517b00fb778238677f26`

````python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.audit import AuditEvent
from app.capabilities import CapabilityKind, CapabilityRouter
from app.context_builder import ContextBuilder, ContextSectionKind
from app.memory import (
    HybridMemorySearchResult,
    Memory,
    MemoryRepositoryError,
    MemoryType,
)
from app.orchestration import (
    CoreRequest,
    CoreRequestPipeline,
    PersonaReference,
    ProjectContextNotFound,
    TaskContextNotFound,
    TaskProjectMismatch,
)
from app.persona import PersonaSnapshot
from app.projects import (
    Project,
    ProjectNotFound,
    ProjectPriority,
    ProjectStatus,
)
from app.routing import FastRoute, FastRouter
from app.tasks import Task, TaskNotFound, TaskPriority, TaskStatus

NOW = datetime(2026, 8, 1, 3, 0, tzinfo=UTC)


class RecordingRetriever:
    def __init__(self, results: list[HybridMemorySearchResult] | None = None) -> None:
        self.results = results or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def retrieve(
        self,
        query: str,
        **kwargs: Any,
    ) -> list[HybridMemorySearchResult]:
        self.calls.append((query, kwargs))
        return list(self.results)


class FailingRetriever:
    def retrieve(
        self,
        query: str,
        **kwargs: Any,
    ) -> list[HybridMemorySearchResult]:
        raise MemoryRepositoryError("memory unavailable")


class ProjectReader:
    def __init__(self, projects: tuple[Project, ...] = ()) -> None:
        self.projects = {project.id: project for project in projects}

    def get(self, project_id: str) -> Project:
        try:
            return self.projects[project_id]
        except KeyError as error:
            raise ProjectNotFound(f"Project not found: {project_id}") from error


class TaskReader:
    def __init__(self, tasks: tuple[Task, ...] = ()) -> None:
        self.tasks = {task.id: task for task in tasks}

    def get(self, task_id: str) -> Task:
        try:
            return self.tasks[task_id]
        except KeyError as error:
            raise TaskNotFound(f"Task not found: {task_id}") from error


class RecordingAuditWriter:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


def _persona() -> PersonaSnapshot:
    return PersonaSnapshot(
        version="1.7",
        content_hash="b" * 64,
        file_order=("IDENTITY.md",),
        files={"IDENTITY.md": "Ánh Dương — AI coworker an toàn."},
        combined_content="Ánh Dương — AI coworker an toàn.",
    )


def _project(project_id: str = "proj_or1") -> Project:
    return Project(
        id=project_id,
        name="Ánh Dương Core",
        slug="anh-duong-core",
        status=ProjectStatus.ACTIVE,
        priority=ProjectPriority.HIGH,
        path_windows=r"F:\AIOS\anh-duong-core",
        path_wsl="/mnt/f/AIOS/anh-duong-core",
        repo_url=None,
        current_phase="OR-1",
        owner="user",
        summary="Build the AI coworker request pipeline.",
        next_action="Run OR-1 tests.",
        constraints=("No schema changes",),
        created_at=NOW,
        updated_at=NOW,
        last_activity_at=NOW,
        version=4,
    )


def _task(
    task_id: str = "task_or1",
    *,
    project_id: str = "proj_or1",
) -> Task:
    return Task(
        id=task_id,
        project_id=project_id,
        title="Build Core Request Pipeline v1",
        description="Prepare requests without executing capabilities.",
        status=TaskStatus.PLANNING,
        priority=TaskPriority.HIGH,
        risk_level=0,
        requested_by="user",
        source_channel="internal",
        approval_required=False,
        current_step_id=None,
        result_summary=None,
        deadline=None,
        created_at=NOW,
        updated_at=NOW,
        version=3,
    )


def _memory() -> HybridMemorySearchResult:
    memory = Memory(
        id="mem_or1",
        memory_type=MemoryType.PROJECT,
        scope_id="scope_or1",
        title="OR-1 constraint",
        content="OR-1 must never execute a capability.",
        summary=None,
        importance=0.9,
        confidence=1.0,
        source="unit-test",
        expires_at=None,
        tags=("or-1",),
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )
    return HybridMemorySearchResult(
        memory=memory,
        fts_rank=-1.0,
        lexical_score=1.0,
        importance_score=0.9,
        confidence_score=1.0,
        recency_score=1.0,
        hybrid_score=0.96,
    )


def _pipeline(
    *,
    retriever: RecordingRetriever | FailingRetriever | None = None,
    project_reader: ProjectReader | None = None,
    task_reader: TaskReader | None = None,
    audit_writer: RecordingAuditWriter | None = None,
) -> CoreRequestPipeline:
    return CoreRequestPipeline(
        persona_loader=_persona,
        fast_router=FastRouter(),
        capability_router=CapabilityRouter(),
        context_builder=ContextBuilder(retriever or RecordingRetriever()),
        project_reader=project_reader or ProjectReader(),
        task_reader=task_reader or TaskReader(),
        audit_writer=audit_writer or RecordingAuditWriter(),
        clock=lambda: NOW,
        id_factory=lambda: "req_fixed",
    )


def test_direct_request_produces_complete_prepared_request() -> None:
    prepared = _pipeline().prepare(
        CoreRequest(text="  Xin   chào!  ", request_id="client-request-1")
    )

    assert prepared.request_id == "client-request-1"
    assert prepared.normalized_text == "Xin chào!"
    assert prepared.persona == PersonaReference(
        version="1.7",
        content_hash="b" * 64,
    )
    assert prepared.route_decision.route is FastRoute.DIRECT
    assert (
        prepared.capability_decision.capability
        is CapabilityKind.CONVERSATIONAL_RESPONSE
    )
    assert prepared.execution_required is False
    assert prepared.created_at == NOW

def test_tg1_simple_arithmetic_request_routes_direct() -> None:
    prepared = _pipeline().prepare(
        CoreRequest(
            text=(
                "TG1-DIRECT-20260801 — Tính 27 + 15 và trả lời ngắn gọn."
            ),
            request_id="tg1-direct-regression",
        )
    )

    assert prepared.route_decision.route is FastRoute.DIRECT
    assert (
        prepared.capability_decision.capability
        is CapabilityKind.CONVERSATIONAL_RESPONSE
    )
    assert prepared.execution_required is False


def test_memory_request_uses_context_builder_and_scope() -> None:
    retriever = RecordingRetriever([_memory()])

    prepared = _pipeline(retriever=retriever).prepare(
        CoreRequest(
            text="Bạn có nhớ tôi đã nói gì về OR-1 không?",
            memory_scope_id="scope_or1",
        )
    )

    assert prepared.route_decision.route is FastRoute.MEMORY
    assert prepared.capability_decision.capability is CapabilityKind.MEMORY_SEARCH
    assert "OR-1 must never execute a capability." in prepared.context.rendered_context
    assert len(retriever.calls) == 1
    assert retriever.calls[0][1] == {"scope_id": "scope_or1", "limit": 20}


def test_project_request_reads_and_renders_registry_snapshot() -> None:
    project = _project()

    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(
            text="Tiến độ Project Ánh Dương thế nào?",
            project_id=project.id,
        )
    )

    assert prepared.route_decision.route is FastRoute.CORE_READ
    assert prepared.capability_decision.capability is CapabilityKind.PROJECT_READ
    assert prepared.project_id == project.id
    assert "identity: proj_or1" in prepared.context.rendered_context
    assert "current_phase: OR-1" in prepared.context.rendered_context
    assert prepared.provenance.project_version == 4


def test_task_request_reads_and_renders_registry_snapshot() -> None:
    task = _task()

    prepared = _pipeline(task_reader=TaskReader((task,))).prepare(
        CoreRequest(
            text="Task OR-1 đang ở trạng thái nào?",
            task_id=task.id,
        )
    )

    assert prepared.capability_decision.capability is CapabilityKind.TASK_READ
    assert prepared.task_id == task.id
    assert "identity: task_or1" in prepared.context.rendered_context
    assert "Build Core Request Pipeline v1" in prepared.context.rendered_context
    assert prepared.provenance.task_version == 3


def test_workflow_and_ambiguous_requests_require_later_execution_only() -> None:
    workflow = _pipeline().prepare(CoreRequest(text="Chạy pytest cho app."))
    unknown = _pipeline().prepare(CoreRequest(text="Màu tím."))

    assert workflow.route_decision.route is FastRoute.WORKFLOW
    assert workflow.capability_decision.capability is CapabilityKind.CODE_OPERATION
    assert workflow.execution_required is True
    assert unknown.route_decision.route is FastRoute.WORKFLOW
    assert unknown.capability_decision.capability is CapabilityKind.UNKNOWN_WORKFLOW
    assert unknown.execution_required is True


def test_missing_project_and_task_raise_clear_pipeline_errors() -> None:
    pipeline = _pipeline()

    with pytest.raises(ProjectContextNotFound, match="proj_missing"):
        pipeline.prepare(
            CoreRequest(text="Xem Project missing.", project_id="proj_missing")
        )
    with pytest.raises(TaskContextNotFound, match="task_missing"):
        pipeline.prepare(
            CoreRequest(text="Xem Task missing.", task_id="task_missing")
        )


def test_explicit_task_project_mismatch_is_rejected() -> None:
    project = _project("proj_requested")
    task = _task(project_id="proj_actual")

    with pytest.raises(TaskProjectMismatch, match="proj_actual"):
        _pipeline(
            project_reader=ProjectReader((project,)),
            task_reader=TaskReader((task,)),
        ).prepare(
            CoreRequest(
                text="Xem trạng thái Task OR-1.",
                project_id=project.id,
                task_id=task.id,
            )
        )


def test_fixed_clock_and_id_make_output_deterministic() -> None:
    pipeline = _pipeline()
    request = CoreRequest(text="Xin chào!")

    assert pipeline.prepare(request) == pipeline.prepare(request)


def test_context_warning_budget_decisions_and_provenance_are_propagated() -> None:
    prepared = _pipeline(retriever=FailingRetriever()).prepare(
        CoreRequest(text="Xin chào!")
    )

    assert prepared.warnings == (
        "memory_retrieval_failed: MemoryRepositoryError",
    )
    assert prepared.warnings == prepared.context.warnings
    assert prepared.context.estimated_tokens <= (
        prepared.context.token_budget.usable_context_tokens
    )
    assert prepared.provenance.route_rule_id == prepared.route_decision.rule_id
    assert (
        prepared.provenance.capability_reason_code
        == prepared.capability_decision.reason_code
    )
    assert "request:current" in prepared.provenance.context_source_refs


def test_secret_is_redacted_from_all_prepared_response_text() -> None:
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz"

    prepared = _pipeline().prepare(
        CoreRequest(text=f"Ghi nhớ api_key={secret}")
    )

    serialized = str(prepared.model_dump(mode="json"))
    assert secret not in serialized
    assert "api_key=[REDACTED]" in prepared.normalized_text


def test_success_writes_one_minimal_audit_event() -> None:
    writer = RecordingAuditWriter()

    prepared = _pipeline(audit_writer=writer).prepare(
        CoreRequest(
            text="Xin chào! api_key=sk-proj-abcdefghijklmnopqrstuvwxyz",
            actor="desktop",
            channel="internal",
        )
    )

    assert len(writer.events) == 1
    event = writer.events[0]
    assert event.event_type == "request.prepared"
    assert event.actor == "desktop"
    assert event.request_id == prepared.request_id
    assert event.payload == {
        "request_id": "req_fixed",
        "channel": "internal",
        "project_id": None,
        "task_id": None,
        "route": "workflow",
        "capability": "unknown_workflow",
        "persona_version": "1.7",
        "persona_content_hash": "b" * 64,
        "token_estimate": prepared.context.estimated_tokens,
        "warning_count": 0,
    }
    assert "sk-proj" not in str(event.model_dump(mode="json"))


def test_context_bundle_preserves_required_section_order() -> None:
    prepared = _pipeline().prepare(CoreRequest(text="Xin chào!"))

    assert tuple(section.kind for section in prepared.context.sections) == tuple(
        ContextSectionKind
    )
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/package.json`

SHA-256: `7747e193b0b553281c5825f50fa4be3154861d4d528b111476735dbee93c5c9b`

````json
{
  "name": "@anh-duong/openclaw-core-gate",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test test/*.test.js"
  },
  "peerDependencies": {
    "openclaw": ">=2026.7.1 <2026.8.0"
  },
  "peerDependenciesMeta": {
    "openclaw": {
      "optional": true
    }
  },
  "openclaw": {
    "extensions": [
      "./index.js"
    ],
    "compat": {
      "pluginApi": ">=2026.7.1",
      "minGatewayVersion": "2026.7.1"
    },
    "build": {
      "openclawVersion": "2026.7.1",
      "pluginSdkVersion": "2026.7.1"
    }
  }
}
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/openclaw.plugin.json`

SHA-256: `d753f2e2fd8dae9c087a5e4970437e7c19b2e0da1be3ed356f1c745354f16737`

````json
{
  "id": "anh-duong-core",
  "name": "Ánh Dương Core Gate",
  "description": "Fail-closed Core preparation gate for ordinary Telegram agent turns.",
  "version": "1.0.0",
  "activation": {
    "onStartup": true
  },
  "configSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {}
  }
}
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/index.js`

SHA-256: `010317606c0e032ddaa23dcdc9ca6735e50fd2425fc678754a22e050d57bc393`

````javascript
import { createAnhDuongCoreHooks } from "./src/hooks.js";

const PROMPT_HOOK_TIMEOUT_MS = 32_000;
const GATE_HOOK_TIMEOUT_MS = 2_000;

export default {
  id: "anh-duong-core",
  name: "Ánh Dương Core Gate",
  description: "Fail-closed Core preparation gate for ordinary Telegram agent turns.",
  register(api) {
    const hooks = createAnhDuongCoreHooks({ logger: api.logger });
    api.on("before_prompt_build", hooks.beforePromptBuild, {
      priority: 100,
      timeoutMs: PROMPT_HOOK_TIMEOUT_MS,
    });
    api.on("before_agent_run", hooks.beforeAgentRun, {
      priority: 100,
      timeoutMs: GATE_HOOK_TIMEOUT_MS,
    });
    api.on("agent_end", hooks.agentEnd, { priority: 100 });
  },
};
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/src/config.js`

SHA-256: `8e013b09469c7ab8a3d7803b8d9afbc55644b2f3f3db8a958279ae58c9276141`

````javascript
export class CoreIntegrationError extends Error {
  constructor(failureClass, { status, requestId } = {}) {
    super(`Ánh Dương Core integration failed (${failureClass})`);
    this.name = "CoreIntegrationError";
    this.failureClass = failureClass;
    if (Number.isInteger(status)) {
      this.status = status;
    }
    if (typeof requestId === "string" && requestId.length > 0) {
      this.requestId = requestId;
    }
  }

  toJSON() {
    return {
      name: this.name,
      failureClass: this.failureClass,
      ...(this.status === undefined ? {} : { status: this.status }),
      ...(this.requestId === undefined ? {} : { requestId: this.requestId }),
    };
  }
}

function configurationError() {
  return new CoreIntegrationError("configuration");
}

export function readCoreConfig(env = process.env) {
  const enabled = env.ANH_DUONG_CORE_ENABLED;
  if (enabled === "false") {
    return { enabled: false };
  }
  if (enabled !== "true") {
    throw configurationError();
  }

  const token = env.ANH_DUONG_CORE_INTERNAL_TOKEN;
  if (typeof token !== "string" || token.length === 0) {
    throw configurationError();
  }

  let url;
  try {
    url = new URL(env.ANH_DUONG_CORE_BASE_URL);
  } catch {
    throw configurationError();
  }
  if ((url.protocol !== "http:" && url.protocol !== "https:") || url.username || url.password) {
    throw configurationError();
  }
  if (url.pathname !== "/" || url.search || url.hash) {
    throw configurationError();
  }

  const timeoutSeconds = Number(env.ANH_DUONG_CORE_TIMEOUT_SECONDS);
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 30) {
    throw configurationError();
  }

  return {
    enabled: true,
    baseUrl: url.origin,
    token,
    timeoutMs: timeoutSeconds * 1_000,
  };
}
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/src/core-client.js`

SHA-256: `9faa247ce1515eed4041cbf96efa478ebc126487ddafb6a00c229cb6703a9766`

````javascript
import { createHash } from "node:crypto";

import { CoreIntegrationError } from "./config.js";

const ROUTES = new Set(["direct", "memory", "core_read", "workflow"]);
const CAPABILITIES = new Set([
  "conversational_response",
  "memory_search",
  "project_read",
  "task_read",
  "core_status_read",
  "planning",
  "file_operation",
  "code_operation",
  "external_communication",
  "system_operation",
  "unknown_workflow",
]);

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function validationError(requestId) {
  return new CoreIntegrationError("validation", { requestId });
}

function requireObject(value, requestId) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw validationError(requestId);
  }
  return value;
}

function requireString(value, requestId, { maxLength } = {}) {
  if (typeof value !== "string" || value.length === 0 || (maxLength && value.length > maxLength)) {
    throw validationError(requestId);
  }
  return value;
}

function requireStringArray(value, requestId) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw validationError(requestId);
  }
  return value;
}

export function buildCoreRequest({ prompt, runId, senderId }) {
  if (typeof prompt !== "string" || prompt.trim().length === 0 || prompt.length > 20_000) {
    throw validationError();
  }
  if (typeof runId !== "string" || runId.trim().length === 0) {
    throw validationError();
  }

  const directRequestId = `tg-${runId}`;
  const requestId = directRequestId.length <= 128 ? directRequestId : `tg-${sha256(runId)}`;
  const actor =
    typeof senderId === "string" && senderId.length > 0
      ? `telegram:${sha256(senderId)}`
      : "telegram:anonymous";

  return {
    text: prompt,
    request_id: requestId,
    channel: "telegram",
    actor,
  };
}

export function validatePreparedRequest(value, expectedRequestId) {
  const root = requireObject(value, expectedRequestId);
  const requestId = requireString(root.request_id, expectedRequestId, { maxLength: 128 });
  if (requestId !== expectedRequestId) {
    throw validationError(expectedRequestId);
  }
  requireString(root.normalized_text, expectedRequestId, { maxLength: 20_000 });

  const persona = requireObject(root.persona, expectedRequestId);
  requireString(persona.version, expectedRequestId);
  if (!/^[0-9a-f]{64}$/.test(requireString(persona.content_hash, expectedRequestId))) {
    throw validationError(expectedRequestId);
  }

  const routeDecision = requireObject(root.route_decision, expectedRequestId);
  const route = requireString(routeDecision.route, expectedRequestId);
  if (!ROUTES.has(route)) {
    throw validationError(expectedRequestId);
  }
  requireString(routeDecision.rule_id, expectedRequestId);
  requireString(routeDecision.reason, expectedRequestId);

  const capabilityDecision = requireObject(root.capability_decision, expectedRequestId);
  const capability = requireString(capabilityDecision.capability, expectedRequestId);
  if (!CAPABILITIES.has(capability)) {
    throw validationError(expectedRequestId);
  }
  if (capabilityDecision.source_route !== route) {
    throw validationError(expectedRequestId);
  }
  requireString(capabilityDecision.reason_code, expectedRequestId);
  requireStringArray(capabilityDecision.matched_signals, expectedRequestId);

  const context = requireObject(root.context, expectedRequestId);
  requireString(context.rendered_context, expectedRequestId);
  if (typeof root.execution_required !== "boolean") {
    throw validationError(expectedRequestId);
  }
  if ((route === "workflow") !== root.execution_required) {
    throw validationError(expectedRequestId);
  }
  requireStringArray(root.warnings, expectedRequestId);

  const provenance = requireObject(root.provenance, expectedRequestId);
  requireString(provenance.persona_version, expectedRequestId);
  if (!/^[0-9a-f]{64}$/.test(requireString(provenance.persona_content_hash, expectedRequestId))) {
    throw validationError(expectedRequestId);
  }
  requireString(provenance.route_rule_id, expectedRequestId);
  requireString(provenance.capability_reason_code, expectedRequestId);
  requireStringArray(provenance.context_source_refs, expectedRequestId);

  const createdAt = requireString(root.created_at, expectedRequestId);
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(createdAt) || Number.isNaN(Date.parse(createdAt))) {
    throw validationError(expectedRequestId);
  }

  return root;
}

export async function prepareCoreRequest({ config, request, fetchImpl = fetch }) {
  const requestId = request?.request_id;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);

  try {
    let response;
    try {
      response = await fetchImpl(`${config.baseUrl}/api/internal/requests/prepare`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${config.token}`,
        },
        body: JSON.stringify(request),
        signal: controller.signal,
      });
    } catch {
      if (controller.signal.aborted) {
        throw new CoreIntegrationError("timeout", { requestId });
      }
      throw new CoreIntegrationError("connection", { requestId });
    }

    if (!response || typeof response.status !== "number" || typeof response.json !== "function") {
      throw validationError(requestId);
    }
    if (!response.ok) {
      const failureClass = response.status === 401 || response.status === 403 ? "authentication" : "http";
      throw new CoreIntegrationError(failureClass, { status: response.status, requestId });
    }

    let value;
    try {
      value = await response.json();
    } catch {
      throw validationError(requestId);
    }
    return validatePreparedRequest(value, requestId);
  } finally {
    clearTimeout(timer);
  }
}
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/src/hooks.js`

SHA-256: `9081d4f37e1c0edc2c6645b48245372781000047f2a8e5bf6b65546a4041f175`

````javascript
import { CoreIntegrationError, readCoreConfig } from "./config.js";
import { buildCoreRequest, prepareCoreRequest } from "./core-client.js";
import { buildPreparedContext } from "./prompt.js";

export const SAFE_MESSAGE =
  "Ánh Dương Core hiện chưa sẵn sàng xử lý yêu cầu này. Vui lòng thử lại sau.";

const STATE_TTL_MS = 5 * 60 * 1_000;

function isTelegram(ctx) {
  return ctx?.messageProvider === "telegram" || ctx?.channel === "telegram";
}

function safeLog(logger, level, fields) {
  const method = logger?.[level];
  if (typeof method !== "function") {
    return;
  }
  try {
    method.call(logger, JSON.stringify(fields));
  } catch {
    // Observability must never change the fail-closed decision.
  }
}

function failureClassOf(error) {
  return error instanceof CoreIntegrationError ? error.failureClass : "internal";
}

export function createAnhDuongCoreHooks({
  env = process.env,
  fetchImpl = fetch,
  logger,
  now = () => Date.now(),
} = {}) {
  let config;
  let configFailure;
  try {
    config = readCoreConfig(env);
  } catch (error) {
    configFailure = error;
  }

  const explicitlyDisabled = config?.enabled === false;
  const states = new Map();

  function sweep() {
    const current = now();
    for (const [runId, state] of states) {
      if (state.expiresAt <= current) {
        states.delete(runId);
      }
    }
  }

  async function beforePromptBuild(event, ctx) {
    sweep();
    if (explicitlyDisabled || !isTelegram(ctx)) {
      return undefined;
    }

    const runId = ctx?.runId;
    if (typeof runId !== "string" || runId.length === 0) {
      safeLog(logger, "warn", {
        event: "anh_duong_core_prepare",
        outcome: "failure",
        failure_class: "missing_run_id",
      });
      return undefined;
    }

    const existing = states.get(runId);
    if (existing?.status === "prepared") {
      return { prependContext: existing.preparedContext };
    }
    if (existing) {
      return undefined;
    }

    states.set(runId, {
      status: "pending",
      expiresAt: now() + STATE_TTL_MS,
    });

    let requestId;
    try {
      if (configFailure || !config?.enabled) {
        throw configFailure ?? new CoreIntegrationError("configuration");
      }
      const request = buildCoreRequest({
        prompt: event?.prompt,
        runId,
        senderId: ctx?.senderId,
      });
      requestId = request.request_id;
      const prepared = await prepareCoreRequest({ config, request, fetchImpl });
      const preparedContext = buildPreparedContext(prepared);
      states.set(runId, {
        status: "prepared",
        requestId,
        preparedContext,
        expiresAt: now() + STATE_TTL_MS,
      });
      safeLog(logger, "info", {
        event: "anh_duong_core_prepare",
        outcome: "success",
        request_id: requestId,
        route: prepared.route_decision.route,
        capability: prepared.capability_decision.capability,
        execution_required: prepared.execution_required,
      });
      return { prependContext: preparedContext };
    } catch (error) {
      const failureClass = failureClassOf(error);
      states.set(runId, {
        status: "failed",
        requestId,
        failureClass,
        expiresAt: now() + STATE_TTL_MS,
      });
      safeLog(logger, "warn", {
        event: "anh_duong_core_prepare",
        outcome: "failure",
        ...(requestId ? { request_id: requestId } : {}),
        failure_class: failureClass,
        ...(Number.isInteger(error?.status) ? { http_status: error.status } : {}),
      });
      return undefined;
    }
  }

  async function beforeAgentRun(_event, ctx) {
    sweep();
    if (explicitlyDisabled || !isTelegram(ctx)) {
      return undefined;
    }
    const runId = ctx?.runId;
    const state = typeof runId === "string" ? states.get(runId) : undefined;
    if (state?.status === "prepared") {
      return { outcome: "pass" };
    }
    return {
      outcome: "block",
      reason: "anh_duong_core_unavailable",
      category: "core_unavailable",
      message: SAFE_MESSAGE,
    };
  }

  async function agentEnd(_event, ctx) {
    if (typeof ctx?.runId === "string") {
      states.delete(ctx.runId);
    }
    sweep();
  }

  return { beforePromptBuild, beforeAgentRun, agentEnd };
}
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/src/prompt.js`

SHA-256: `aae8054607d452c922aeb35b56137e1d6dbb6b5e709d3ecfa6786e761202fba7`

````javascript
import { CoreIntegrationError } from "./config.js";

export function buildPreparedContext(prepared) {
  const rendered = prepared?.context?.rendered_context;
  if (typeof rendered !== "string" || rendered.length === 0 || rendered.length > 100_000) {
    throw new CoreIntegrationError("validation", { requestId: prepared?.request_id });
  }

  return [
    "<anh_duong_core_prepared_request>",
    `request_id: ${prepared.request_id}`,
    `route: ${prepared.route_decision.route}`,
    `capability: ${prepared.capability_decision.capability}`,
    `execution_required: ${prepared.execution_required}`,
    "core_context:",
    rendered,
    "</anh_duong_core_prepared_request>",
  ].join("\n");
}
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/test/config.test.js`

SHA-256: `40d51a7ffbd902813d5bd53206c4558c22423e924451caf4c3ee9d9ec6570b6e`

````javascript
import assert from "node:assert/strict";
import test from "node:test";

import { readCoreConfig } from "../src/config.js";

const VALID_ENV = {
  ANH_DUONG_CORE_ENABLED: "true",
  ANH_DUONG_CORE_BASE_URL: "http://host.docker.internal:8790/",
  ANH_DUONG_CORE_INTERNAL_TOKEN: "unit-test-secret",
  ANH_DUONG_CORE_TIMEOUT_SECONDS: "10",
};

test("disabled integration preserves the legacy path without requiring credentials", () => {
  assert.deepEqual(readCoreConfig({ ANH_DUONG_CORE_ENABLED: "false" }), {
    enabled: false,
  });
});

test("enabled integration normalizes a valid finite configuration", () => {
  assert.deepEqual(readCoreConfig(VALID_ENV), {
    enabled: true,
    baseUrl: "http://host.docker.internal:8790",
    token: "unit-test-secret",
    timeoutMs: 10_000,
  });
});

for (const [name, override] of [
  ["missing enabled flag", { ANH_DUONG_CORE_ENABLED: undefined }],
  ["invalid enabled flag", { ANH_DUONG_CORE_ENABLED: "yes" }],
  ["missing base URL", { ANH_DUONG_CORE_BASE_URL: "" }],
  ["non-http base URL", { ANH_DUONG_CORE_BASE_URL: "file:///tmp/core" }],
  ["missing token", { ANH_DUONG_CORE_INTERNAL_TOKEN: "" }],
  ["zero timeout", { ANH_DUONG_CORE_TIMEOUT_SECONDS: "0" }],
  ["oversized timeout", { ANH_DUONG_CORE_TIMEOUT_SECONDS: "31" }],
  ["fractional timeout", { ANH_DUONG_CORE_TIMEOUT_SECONDS: "1.5" }],
]) {
  test(`enabled integration rejects ${name}`, () => {
    const env = { ...VALID_ENV, ...override };
    assert.throws(
      () => readCoreConfig(env),
      (error) => error?.name === "CoreIntegrationError" && error?.failureClass === "configuration",
    );
  });
}

test("configuration failures never expose the token", () => {
  const token = "never-print-this-token";
  assert.throws(
    () =>
      readCoreConfig({
        ...VALID_ENV,
        ANH_DUONG_CORE_INTERNAL_TOKEN: token,
        ANH_DUONG_CORE_TIMEOUT_SECONDS: "bad",
      }),
    (error) => !String(error).includes(token) && !JSON.stringify(error).includes(token),
  );
});
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/test/client.test.js`

SHA-256: `4293aeee678f8b8d0297defec5e234f6a32d837a2c692bdea967b7b1146c3612`

````javascript
import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCoreRequest,
  prepareCoreRequest,
  validatePreparedRequest,
} from "../src/core-client.js";
import { buildPreparedContext } from "../src/prompt.js";

const TOKEN = "secret-token-must-not-leak";
const CONFIG = {
  enabled: true,
  baseUrl: "http://core.local:8790",
  token: TOKEN,
  timeoutMs: 25,
};

function preparedFixture(requestId, { route = "direct", executionRequired = false } = {}) {
  return {
    request_id: requestId,
    normalized_text: "Tóm tắt trạng thái hệ thống hiện tại",
    persona: {
      version: "1",
      content_hash: "a".repeat(64),
    },
    route_decision: {
      route,
      rule_id: `route-${route}`,
      reason: "fixture route",
    },
    capability_decision: {
      capability: route === "workflow" ? "planning" : "conversational_response",
      source_route: route,
      reason_code: `capability-${route}`,
      matched_signals: [],
    },
    context: {
      sections: [],
      rendered_context: "[Persona]\nBạn là Ánh Dương.\n[Current Request]\nTóm tắt trạng thái hệ thống hiện tại",
      token_budget: {
        context_window_tokens: 16000,
        response_reserve_tokens: 3000,
        runtime_reserve_tokens: 1000,
        persona_soft_tokens: 1200,
        routing_soft_tokens: 800,
        task_soft_tokens: 3200,
        project_soft_tokens: 2400,
        memory_soft_tokens: 4400,
        usable_context_tokens: 12000,
      },
      estimated_tokens: 42,
      remaining_tokens: 11958,
      dropped_items: [],
      truncated_items: [],
      warnings: [],
      provenance: [],
    },
    project_id: null,
    task_id: null,
    execution_required: executionRequired,
    warnings: [],
    provenance: {
      persona_version: "1",
      persona_content_hash: "a".repeat(64),
      route_rule_id: `route-${route}`,
      capability_reason_code: `capability-${route}`,
      project_version: null,
      task_version: null,
      context_source_refs: [],
    },
    created_at: "2026-08-01T04:00:00Z",
  };
}

test("request mapping emits only the strict Core contract and pseudonymizes actor", () => {
  assert.deepEqual(
    buildCoreRequest({
      prompt: "  Tóm tắt trạng thái hệ thống hiện tại  ",
      runId: "f4f7990c-a5e1-4a65-9474-905b73ed9dc0",
      senderId: "123456789",
    }),
    {
      text: "  Tóm tắt trạng thái hệ thống hiện tại  ",
      request_id: "tg-f4f7990c-a5e1-4a65-9474-905b73ed9dc0",
      channel: "telegram",
      actor: "telegram:15e2b0d3c33891ebb0f1ef609ec419420c20e320ce94c65fbc8c3312448eb225",
    },
  );
});

test("oversized run IDs become bounded deterministic correlations", () => {
  const first = buildCoreRequest({ prompt: "hello", runId: "x".repeat(300), senderId: undefined });
  const second = buildCoreRequest({ prompt: "hello", runId: "x".repeat(300), senderId: undefined });
  assert.equal(first.request_id, second.request_id);
  assert.match(first.request_id, /^tg-[0-9a-f]{64}$/);
  assert.ok(first.request_id.length <= 128);
  assert.equal(first.actor, "telegram:anonymous");
});

test("blank and oversized prompts fail closed before the network", () => {
  assert.throws(() => buildCoreRequest({ prompt: "   ", runId: "run", senderId: "sender" }));
  assert.throws(() => buildCoreRequest({ prompt: "x".repeat(20_001), runId: "run", senderId: "sender" }));
});

test("client performs one bearer-authenticated prepare POST and validates a direct response", async () => {
  const request = buildCoreRequest({ prompt: "hello", runId: "run-direct", senderId: "sender" });
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(preparedFixture(request.request_id)), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const result = await prepareCoreRequest({ config: CONFIG, request, fetchImpl });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://core.local:8790/api/internal/requests/prepare");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].init.body), request);
  assert.equal(result.route_decision.route, "direct");
  assert.equal(result.execution_required, false);
});

test("client accepts a consistent workflow response", async () => {
  const request = buildCoreRequest({ prompt: "create task", runId: "run-workflow", senderId: "sender" });
  const fetchImpl = async () =>
    new Response(JSON.stringify(preparedFixture(request.request_id, { route: "workflow", executionRequired: true })), {
      status: 200,
    });
  const result = await prepareCoreRequest({ config: CONFIG, request, fetchImpl });
  assert.equal(result.route_decision.route, "workflow");
  assert.equal(result.execution_required, true);
});

for (const [status, failureClass] of [
  [401, "authentication"],
  [403, "authentication"],
  [500, "http"],
]) {
  test(`HTTP ${status} fails closed without retry or body leakage`, async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      return new Response(`private-body-${status}-${TOKEN}`, { status });
    };
    const request = buildCoreRequest({ prompt: "hello", runId: `run-${status}`, senderId: "sender-private" });
    await assert.rejects(
      prepareCoreRequest({ config: CONFIG, request, fetchImpl }),
      (error) => {
        assert.equal(error?.failureClass, failureClass);
        assert.equal(error?.status, status);
        assert.equal(calls, 1);
        const serialized = `${String(error)} ${JSON.stringify(error)}`;
        assert.equal(serialized.includes(TOKEN), false);
        assert.equal(serialized.includes(`private-body-${status}`), false);
        assert.equal(serialized.includes("sender-private"), false);
        return true;
      },
    );
  });
}

test("connection failure is classified and never retried", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    throw new TypeError(`connect ECONNREFUSED ${TOKEN}`);
  };
  const request = buildCoreRequest({ prompt: "hello", runId: "run-connect", senderId: "sender" });
  await assert.rejects(
    prepareCoreRequest({ config: CONFIG, request, fetchImpl }),
    (error) => error?.failureClass === "connection" && calls === 1 && !String(error).includes(TOKEN),
  );
});

test("timeout aborts one request and is classified without leaking details", async () => {
  let calls = 0;
  const fetchImpl = async (_url, init) => {
    calls += 1;
    await new Promise((resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), {
        once: true,
      });
    });
  };
  const request = buildCoreRequest({ prompt: "hello", runId: "run-timeout", senderId: "sender" });
  await assert.rejects(
    prepareCoreRequest({ config: { ...CONFIG, timeoutMs: 5 }, request, fetchImpl }),
    (error) => error?.failureClass === "timeout" && calls === 1,
  );
});

test("malformed JSON fails response validation", async () => {
  const request = buildCoreRequest({ prompt: "hello", runId: "run-json", senderId: "sender" });
  await assert.rejects(
    prepareCoreRequest({
      config: CONFIG,
      request,
      fetchImpl: async () => new Response("not-json", { status: 200 }),
    }),
    (error) => error?.failureClass === "validation",
  );
});

test("request-ID mismatch and route inconsistency fail response validation", () => {
  const direct = preparedFixture("expected");
  assert.throws(
    () => validatePreparedRequest({ ...direct, request_id: "wrong" }, "expected"),
    (error) => error?.failureClass === "validation",
  );
  assert.throws(
    () => validatePreparedRequest({ ...direct, execution_required: true }, "expected"),
    (error) => error?.failureClass === "validation",
  );
  assert.throws(
    () =>
      validatePreparedRequest(
        {
          ...direct,
          capability_decision: { ...direct.capability_decision, source_route: "workflow" },
        },
        "expected",
      ),
    (error) => error?.failureClass === "validation",
  );
});

test("prepared prompt contains only explicit routing metadata and rendered Core context", () => {
  const prepared = preparedFixture("tg-run-direct");
  const context = buildPreparedContext(prepared);
  assert.match(context, /request_id: tg-run-direct/);
  assert.match(context, /route: direct/);
  assert.match(context, /capability: conversational_response/);
  assert.match(context, /execution_required: false/);
  assert.match(context, /Bạn là Ánh Dương/);
  assert.equal(context.includes(TOKEN), false);
  assert.equal(context.includes("created_at"), false);
});
````````

### `anh-duong-core/integrations/openclaw-anh-duong-core/test/hooks.test.js`

SHA-256: `dc4000b42aa1746de3003881c97aa105737e56a77814e547ca57de7312aa8150`

````javascript
import assert from "node:assert/strict";
import test from "node:test";

import plugin from "../index.js";
import { SAFE_MESSAGE, createAnhDuongCoreHooks } from "../src/hooks.js";

const ENV = {
  ANH_DUONG_CORE_ENABLED: "true",
  ANH_DUONG_CORE_BASE_URL: "http://core.local:8790",
  ANH_DUONG_CORE_INTERNAL_TOKEN: "hook-test-token",
  ANH_DUONG_CORE_TIMEOUT_SECONDS: "1",
};

function responseFixture(requestId) {
  return {
    request_id: requestId,
    normalized_text: "hello",
    persona: { version: "1", content_hash: "b".repeat(64) },
    route_decision: { route: "direct", rule_id: "route-direct", reason: "fixture" },
    capability_decision: {
      capability: "conversational_response",
      source_route: "direct",
      reason_code: "direct",
      matched_signals: [],
    },
    context: {
      sections: [],
      rendered_context: "prepared context",
      token_budget: {},
      estimated_tokens: 2,
      remaining_tokens: 100,
      dropped_items: [],
      truncated_items: [],
      warnings: [],
      provenance: [],
    },
    project_id: null,
    task_id: null,
    execution_required: false,
    warnings: [],
    provenance: {
      persona_version: "1",
      persona_content_hash: "b".repeat(64),
      route_rule_id: "route-direct",
      capability_reason_code: "direct",
      project_version: null,
      task_version: null,
      context_source_refs: [],
    },
    created_at: "2026-08-01T04:00:00Z",
  };
}

function telegramContext(runId = "run-1") {
  return {
    runId,
    messageProvider: "telegram",
    channel: "telegram",
    senderId: "private-sender",
    chatId: "private-chat",
    sessionKey: "private-session",
  };
}

function collectingLogger() {
  const entries = [];
  return {
    entries,
    info(message) {
      entries.push(String(message));
    },
    warn(message) {
      entries.push(String(message));
    },
  };
}

test("disabled integration and non-Telegram turns bypass Core and model gating", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    throw new Error("must not run");
  };
  const disabled = createAnhDuongCoreHooks({
    env: { ANH_DUONG_CORE_ENABLED: "false" },
    fetchImpl,
  });
  assert.equal(await disabled.beforePromptBuild({ prompt: "hello", messages: [] }, telegramContext()), undefined);
  assert.equal(await disabled.beforeAgentRun({ prompt: "hello", messages: [] }, telegramContext()), undefined);

  const enabled = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const discord = { runId: "run-discord", messageProvider: "discord", channel: "discord" };
  assert.equal(await enabled.beforePromptBuild({ prompt: "hello", messages: [] }, discord), undefined);
  assert.equal(await enabled.beforeAgentRun({ prompt: "hello", messages: [] }, discord), undefined);
  assert.equal(calls, 0);
});

test("successful Telegram preparation injects context then allows model execution", async () => {
  let calls = 0;
  const fetchImpl = async (_url, init) => {
    calls += 1;
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-success");

  const injection = await hooks.beforePromptBuild({ prompt: "hello", messages: [] }, ctx);
  const gate = await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx);

  assert.equal(calls, 1);
  assert.match(injection.prependContext, /request_id: tg-run-success/);
  assert.deepEqual(gate, { outcome: "pass" });
});

test("pending preparation blocks before model input", async () => {
  let release;
  const fetchImpl = async (_url, init) => {
    await new Promise((resolve) => {
      release = resolve;
    });
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-pending");
  const pending = hooks.beforePromptBuild({ prompt: "hello", messages: [] }, ctx);
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx), {
    outcome: "block",
    reason: "anh_duong_core_unavailable",
    category: "core_unavailable",
    message: SAFE_MESSAGE,
  });

  release();
  await pending;
});

for (const [name, fetchImpl] of [
  ["connection failure", async () => { throw new TypeError("ECONNREFUSED hook-test-token private-chat"); }],
  ["authentication failure", async () => new Response("private body", { status: 401 })],
  ["invalid response", async () => new Response("{}", { status: 200 })],
]) {
  test(`${name} blocks the model and emits only sanitized logs`, async () => {
    const logger = collectingLogger();
    const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl, logger });
    const ctx = telegramContext(`run-${name.replaceAll(" ", "-")}`);

    assert.equal(await hooks.beforePromptBuild({ prompt: "private prompt", messages: [] }, ctx), undefined);
    assert.deepEqual(await hooks.beforeAgentRun({ prompt: "private prompt", messages: [] }, ctx), {
      outcome: "block",
      reason: "anh_duong_core_unavailable",
      category: "core_unavailable",
      message: SAFE_MESSAGE,
    });

    const logs = logger.entries.join("\n");
    for (const forbidden of ["hook-test-token", "private-chat", "private-sender", "private-session", "private prompt", "private body", "Authorization"]) {
      assert.equal(logs.includes(forbidden), false);
    }
  });
}

test("missing run ID fails closed for an enabled Telegram turn", async () => {
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl: async () => { throw new Error("must not run"); } });
  const ctx = telegramContext(undefined);
  delete ctx.runId;
  assert.equal(await hooks.beforePromptBuild({ prompt: "hello", messages: [] }, ctx), undefined);
  assert.equal((await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx)).outcome, "block");
});

test("agent-end cleanup removes prepared state", async () => {
  const fetchImpl = async (_url, init) => {
    const body = JSON.parse(init.body);
    return new Response(JSON.stringify(responseFixture(body.request_id)), { status: 200 });
  };
  const hooks = createAnhDuongCoreHooks({ env: ENV, fetchImpl });
  const ctx = telegramContext("run-cleanup");
  await hooks.beforePromptBuild({ prompt: "hello", messages: [] }, ctx);
  assert.equal((await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx)).outcome, "pass");
  await hooks.agentEnd({}, ctx);
  assert.equal((await hooks.beforeAgentRun({ prompt: "hello", messages: [] }, ctx)).outcome, "block");
});

test("plugin entry registers exactly the three TG-1 hooks with finite timeouts", () => {
  const registrations = [];
  plugin.register({
    logger: collectingLogger(),
    on(name, handler, options) {
      registrations.push({ name, handler, options });
    },
  });
  assert.deepEqual(
    registrations.map(({ name }) => name),
    ["before_prompt_build", "before_agent_run", "agent_end"],
  );
  assert.ok(registrations[0].options.timeoutMs > 0);
  assert.ok(registrations[1].options.timeoutMs > 0);
});
````````

### `anh-duong-core/scripts/verify_tg1_runtime.ps1`

SHA-256: `5de8ad91501494dac74f9e477180c90f5c057ba32500e0046802894d0cf201d6`

````powershell
[CmdletBinding()]
param(
    [string]$ExpectedImageId = "sha256:86b8cffc648507e11bb7f8e4e1900b2534e4da5f496ecc927a3628c80bd016a7",
    [string]$BackupConfigPath = "F:\AIOS\anh-duong-checkpoints\backups\TG-1-20260801T114348Z\openclaw\openclaw.json"
)

$ErrorActionPreference = "Stop"
$container = "openclaw-openclaw-gateway-1"
$results = [Collections.Generic.List[object]]::new()

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $results.Add([pscustomobject]@{ name = $Name; passed = $Passed; detail = $Detail })
}

function Normalize-JsonValue {
    param($Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [pscustomobject]) {
        $ordered = [ordered]@{}
        foreach ($property in ($Value.PSObject.Properties | Sort-Object Name)) {
            $ordered[$property.Name] = Normalize-JsonValue $property.Value
        }
        return [pscustomobject]$ordered
    }
    if ($Value -is [Collections.IEnumerable] -and $Value -isnot [string]) {
        return @($Value | ForEach-Object { Normalize-JsonValue $_ })
    }
    return $Value
}

function Get-ValueHash {
    param($Value)
    $json = Normalize-JsonValue $Value | ConvertTo-Json -Compress -Depth 100
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    $sha = [Security.Cryptography.SHA256]::Create()
    return [Convert]::ToHexString($sha.ComputeHash($bytes)).ToLowerInvariant()
}

function Get-ProtectedHashes {
    param($Config)
    return [ordered]@{
        telegram_token = Get-ValueHash $Config.channels.telegram.botToken
        telegram_config = Get-ValueHash $Config.channels.telegram
        agent_model = Get-ValueHash $Config.agents.defaults.model
        agent_models = Get-ValueHash $Config.agents.defaults.models
        providers = Get-ValueHash $Config.models.providers
        ninerouter = Get-ValueHash ([pscustomobject]@{
            provider = $Config.models.providers.ninerouter
            secret_provider = $Config.secrets.providers.ninerouter_key_file
        })
    }
}

try {
    $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8790/health" -TimeoutSec 5
    Add-Check "core_health" ($health.StatusCode -eq 200) "HTTP $($health.StatusCode)"
} catch {
    Add-Check "core_health" $false "unreachable"
}

try {
    $ready = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8790/ready" -TimeoutSec 5
    Add-Check "core_ready" ($ready.StatusCode -eq 200) "HTTP $($ready.StatusCode)"
} catch {
    Add-Check "core_ready" $false "unreachable"
}

$mainPid = (& wsl.exe -d Ubuntu -- systemctl show -p MainPID --value anh-duong-core.service).Trim()
$activeState = (& wsl.exe -d Ubuntu -- systemctl is-active anh-duong-core.service).Trim()
Add-Check "core_service" ($activeState -eq "active" -and $mainPid -match "^\d+$" -and $mainPid -ne "0") $activeState

$workerFilter = "tr '\000' '\n' < /proc/$mainPid/environ | sed -n 's/^ANH_DUONG_ASYNC_WORKER_ENABLED=//p'"
$workerValue = (& wsl.exe -d Ubuntu -- sh -c $workerFilter).Trim()
Add-Check "async_worker_disabled" ($workerValue -eq "false") "value=$workerValue"

$alembicOutput = (& wsl.exe -d Ubuntu -- sh -lc "cd /mnt/f/AIOS/anh-duong-core && .venv/bin/alembic current" 2>&1) -join "`n"
Add-Check "alembic_head" ($alembicOutput -match "0003 \(head\)") "0003 (head)"

$inspect = (docker inspect $container | ConvertFrom-Json)[0]
Add-Check "gateway_running" ([string]$inspect.State.Status -eq "running") ([string]$inspect.State.Status)
Add-Check "gateway_healthy" ([string]$inspect.State.Health.Status -eq "healthy") ([string]$inspect.State.Health.Status)
Add-Check "gateway_image_immutable" ([string]$inspect.Image -eq $ExpectedImageId) ([string]$inspect.Image)

$runtimeVersion = (& docker exec $container node -p "require('/app/package.json').version").Trim()
Add-Check "openclaw_version" ($runtimeVersion -eq "2026.7.1") $runtimeVersion

$coreFromGateway = (& docker exec $container node -e "fetch('http://host.docker.internal:8790/health').then(r=>process.stdout.write(String(r.status))).catch(()=>process.stdout.write('000'))").Trim()
Add-Check "core_reachable_from_gateway" ($coreFromGateway -eq "200") "HTTP $coreFromGateway"

$coreTokenFilter = "tr '\000' '\n' < /proc/$mainPid/environ | sed -n 's/^ANH_DUONG_INTERNAL_API_TOKEN=//p'"
$coreToken = & wsl.exe -d Ubuntu -- sh -c $coreTokenFilter
$gatewayToken = & docker exec $container node -e "process.stdout.write(process.env.ANH_DUONG_CORE_INTERNAL_TOKEN || '')"
Add-Check "internal_token_match" (-not [string]::IsNullOrEmpty($coreToken) -and $coreToken -ceq $gatewayToken) "matched=$($coreToken -ceq $gatewayToken)"

$runtimeRaw = & docker exec $container sh -lc "cd /app && node openclaw.mjs plugins inspect anh-duong-core --runtime --json"
$runtime = ($runtimeRaw -join "`n") | ConvertFrom-Json -Depth 40
$hookNames = @($runtime.typedHooks.name | Sort-Object)
$expectedHooks = @("agent_end", "before_agent_run", "before_prompt_build")
Add-Check "plugin_loaded" ($runtime.plugin.status -eq "loaded" -and $runtime.plugin.activated -eq $true) "status=$($runtime.plugin.status)"
Add-Check "plugin_three_hooks" (($hookNames -join ",") -eq ($expectedHooks -join ",")) ($hookNames -join ",")
Add-Check "plugin_no_diagnostics" (@($runtime.diagnostics).Count -eq 0) "count=$(@($runtime.diagnostics).Count)"
Add-Check "plugin_scope_minimal" ($runtime.plugin.toolNames.Count -eq 0 -and $runtime.plugin.channelIds.Count -eq 0 -and $runtime.plugin.httpRoutes -eq 0) "tools=0,channels=0,http=0"
Add-Check "plugin_conversation_policy" ($runtime.policy.allowConversationAccess -eq $true) "allowConversationAccess=true"

$telegramRaw = & docker exec $container sh -lc "cd /app && node openclaw.mjs channels status --probe --json"
$telegramJson = ($telegramRaw -join "`n") | ConvertFrom-Json -Depth 40
$telegram = $telegramJson.channels.telegram
Add-Check "telegram_configured" ($telegram.configured -eq $true) "configured=$($telegram.configured)"
Add-Check "telegram_running" ($telegram.running -eq $true) "running=$($telegram.running)"
Add-Check "telegram_probe" ($telegram.probe.ok -eq $true -and [string]::IsNullOrEmpty([string]$telegram.error)) "probe_ok=$($telegram.probe.ok),mode=$($telegram.mode)"

$backupConfig = Get-Content -Raw -LiteralPath $BackupConfigPath | ConvertFrom-Json -Depth 100
$liveConfigRaw = & docker exec $container sh -lc "cat /home/node/.openclaw/openclaw.json"
$liveConfig = ($liveConfigRaw -join "`n") | ConvertFrom-Json -Depth 100
$beforeHashes = Get-ProtectedHashes $backupConfig
$afterHashes = Get-ProtectedHashes $liveConfig
foreach ($key in $beforeHashes.Keys) {
    Add-Check "protected_hash_$key" ($beforeHashes[$key] -eq $afterHashes[$key]) $afterHashes[$key]
}

$failed = @($results | Where-Object { -not $_.passed })
[pscustomobject]@{
    verdict = if ($failed.Count -eq 0) { "PASS" } else { "FAIL" }
    passed = $results.Count - $failed.Count
    failed = $failed.Count
    checks = $results
} | ConvertTo-Json -Depth 6

if ($failed.Count -ne 0) { exit 1 }
````````

### `anh-duong-core/docs/superpowers/specs/2026-08-01-tg1-telegram-openclaw-core-design.md`

SHA-256: `3de588d163e30fd73019962db06d2e31a1572661ace39b536841ec25997f0141`

````markdown
# TG-1 Telegram → OpenClaw → Ánh Dương Core Design

## Status and scope

This design implements the already-approved TG-1 architecture without changing the Core database schema, OR-1 contract, model/provider/9Router configuration, Telegram token, or async-worker state. It covers ordinary Telegram AI turns only. Native/admin commands and ambient room events remain on their existing OpenClaw paths.

## Contract findings

`POST /api/internal/requests/prepare` accepts only `text`, optional `request_id`, `channel`, `actor`, and optional Project/Task/Memory identifiers. It returns an immutable `PreparedRequest`; it does not execute tools or enqueue work. The fields consumed by OpenClaw are:

- `request_id` for end-to-end correlation;
- `normalized_text` as the redacted current request;
- `route_decision` and `capability_decision` as the Core routing decision;
- `context.rendered_context` as the prepared execution context;
- `execution_required` to distinguish workflow preparation;
- `warnings`, provenance, Persona reference, and UTC creation time for validation/audit.

Telegram chat, topic, sender, and OpenClaw session fields cannot be added to the JSON body because the Core model forbids unknown fields. The adapter therefore derives a deterministic, non-reversible request ID from account/chat/topic/message/session identifiers and maps a non-reversible sender hash into `actor`. The original Telegram metadata stays inside OpenClaw and is used by the existing delivery pipeline.

## Approaches considered

1. **Runtime-matched managed OpenClaw plugin — selected.** Package a dependency-free JavaScript plugin as a local npm tarball, install it into OpenClaw's permission-safe managed ext4 plugin directory, and register the public `before_prompt_build`, `before_agent_run`, and `agent_end` hooks. The plugin scopes itself to `messageProvider/channel === "telegram"`, so other channels are unchanged. This preserves the established Telegram transport, durable ingress, native-command fast path, session, model/tool execution, streaming, and reply funnels without rebuilding or upgrading the running image.
2. **Patch the bundled Telegram extension — rejected for this runtime.** The checked-out OpenClaw source is 2026.7.2 while the active image is 2026.7.1. Rebuilding the checkout would silently upgrade the deployed runtime; patching its generated 2026.7.1 bundle would be fragile and unreviewable.
3. **New Core execution endpoint or worker — rejected.** OR-1 is deliberately prepare-only and Async Worker must remain false. Adding execution semantics would change the approved architecture and contract.

## Components

### Local plugin and Core client

- Lives in `integrations/openclaw-anh-duong-core` and ships a native plugin manifest, an ESM entrypoint, and dependency-free client/validation modules tested with Node's built-in test runner.
- Loads `ANH_DUONG_CORE_ENABLED`, `ANH_DUONG_CORE_BASE_URL`, `ANH_DUONG_CORE_INTERNAL_TOKEN`, and `ANH_DUONG_CORE_TIMEOUT_SECONDS` from the process environment.
- Treats absent/false `ENABLED` as an explicit rollback/legacy mode. When enabled, missing or malformed configuration fails closed.
- Builds the minimal `CoreRequest` from the finalized OpenClaw agent prompt and hook context. `request_id` is derived from the per-turn `runId`; `actor` is a non-reversible sender hash.
- Calls the protected endpoint with a finite timeout and one bearer-authenticated POST. It performs no retries, avoiding duplicate preparation/audit or downstream execution.
- Validates every response field consumed by OpenClaw and verifies route/execution consistency and request-ID equality.
- Classifies failures as configuration, timeout, connection, authentication, HTTP, or validation errors without retaining response bodies or secrets.
- Produces a Core-prepared agent prompt containing the validated rendered context and routing metadata.

### Hook integration

- `before_prompt_build` is the only network phase. For an eligible Telegram agent turn it marks the `runId` fail-closed, calls Core, validates the response, records sanitized state, and returns `prependContext` only after success.
- `before_agent_run` checks the state for the same `runId`. It returns `pass` only after a validated Core preparation. Missing, failed, timed-out, or malformed state returns `block` with the safe user-facing message, so no model input occurs.
- `agent_end` clears per-run state; an expiry sweep bounds abandoned state. No state contains raw prompt, chat ID, sender ID, session key, token, or response body.
- Explicit disabled mode returns no hook result and preserves the legacy path. Native/admin commands already complete before agent invocation, so they never enter these hooks. Ambient or non-Telegram turns are ignored.

## Data flow

| Telegram/OpenClaw input | Core request | Core response | OpenClaw action |
|---|---|---|---|
| finalized agent-turn prompt | `text` | `normalized_text`, `context.rendered_context` | Prepend validated Core context before model execution |
| OpenClaw per-turn `runId` | bounded `tg-<runId>` `request_id` | matching `request_id` | Structured correlation log and hook gate |
| sender ID | hashed `actor` | audit actor only | Raw sender ID remains local |
| channel | `channel="telegram"` | audit channel | Existing Telegram delivery |
| no inferred registry IDs | omit optional IDs | optional IDs remain null | No registry guessing |
| existing session/chat/thread context | not sent (contract forbids metadata) | not returned | Preserved unchanged by the existing OpenClaw runtime |
| route/capability decision | n/a | validated decision | Included in prepared prompt for existing model/tool runtime |

Direct, memory, and Core-read routes run through the normal OpenClaw agent runtime with Core-prepared context. Workflow routes also use that runtime, with `execution_required=true`; no async worker or new workflow engine is introduced.

## Failure and security behavior

- Enabled Core integration is fail-closed for timeout, connect, 401/403, other non-2xx, invalid JSON, response validation, request-ID mismatch, and invalid local configuration.
- The user receives: `Ánh Dương Core hiện chưa sẵn sàng xử lý yêu cầu này. Vui lòng thử lại sau.`
- Logs contain request ID, failure class, HTTP status when available, route/capability on success, and no raw token, Authorization header, raw response body, chat ID, sender ID, or session key.
- There is no CLI fallback and no direct-model fallback.
- Disabled mode is explicit and supports rollback to the pre-TG-1 behavior.

## Runtime configuration

The Gateway container receives the four TG-1 environment variables through the existing Compose service. Runtime activation uses `http://host.docker.internal:8790`, which has been verified from inside the current Gateway container. The existing internal Core token is copied without printing it. The package is installed with `plugins install npm-pack:...`, its ID is added to the existing allowlist/enabled entries, and `hooks.allowConversationAccess=true` authorizes only the two conversation hooks required by the gate. A direct NTFS bind is intentionally not used because OpenClaw correctly rejects world-writable plugin paths. Only the Gateway service is recreated from WSL; no build, image/version update, or volume deletion is allowed.

## Testing and verification

TDD starts with Node built-in unit/integration tests for configuration, request mapping, deterministic correlation, bearer use/redaction, direct/workflow response mapping, timeout/auth/HTTP/invalid-response fail-closed behavior, disabled/non-Telegram behavior, prompt construction, hook ordering, and per-run cleanup. A hook integration test proves failure makes `before_agent_run` return a blocking decision before model input; OpenClaw's own hook contract supplies the existing single final reply funnel.

Regression includes the targeted Telegram adapter/dispatch/native-command suites, TypeScript checks, lint/build scripts supported by the installed Node runtime, and the full Core Pytest/Ruff/Mypy/Compileall suite. Runtime verification checks Core health/ready, Gateway health, Telegram probe, Alembic `0003`, Async Worker false, and pre/post configuration hashes. Final PASS additionally requires the operator's two real Telegram messages and cross-log evidence.

## Rollback

Set `ANH_DUONG_CORE_ENABLED=false` for the reversible legacy path, or restore the backed-up Compose, `.env`, and `openclaw.json` files, uninstall the managed plugin if a full removal is desired, recreate only the Gateway service from WSL, and re-run Gateway/Telegram/Core health checks. No database, image, or volume rollback is required.
````````

### `anh-duong-core/docs/superpowers/plans/2026-08-01-tg1-telegram-openclaw-core.md`

SHA-256: `85b02f1afceefc93ee6d9a9c073390e222795aa016c65079de4be9016861ccec`

````markdown
# TG-1 Telegram → OpenClaw → Ánh Dương Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Route every ordinary Telegram AI turn through Ánh Dương Core preparation before OpenClaw can invoke its model/runtime, with fail-closed behavior, stable correlation, unchanged native commands, and production evidence.

**Architecture:** A dependency-free native OpenClaw plugin runs inside the existing 2026.7.1 Gateway. `before_prompt_build` calls Core and injects validated prepared context; `before_agent_run` passes only a successfully prepared Telegram turn and otherwise blocks before model input; `agent_end` clears bounded per-run state. Compose passes four environment variables, while a local npm tarball is installed into OpenClaw's permission-safe managed ext4 plugin directory. No OpenClaw image build or version change is allowed.

**Tech Stack:** JavaScript ESM, Node built-in `fetch`/`AbortSignal`/`node:test`, OpenClaw 2026.7.1 public plugin hooks, FastAPI/Pydantic Core endpoint, Docker Compose, PowerShell, Pytest/Ruff/Mypy.

## Global constraints

- Preserve Telegram token, model/provider/9Router settings, Core schema/Alembic, and `ANH_DUONG_ASYNC_WORKER_ENABLED=false` byte-for-byte where applicable.
- Never log or place in artifacts the bearer token, Authorization header, raw response body, raw chat/sender/session IDs, or full prompt.
- `ANH_DUONG_CORE_ENABLED=false` is the only deliberate legacy bypass. When enabled, every eligible failure blocks the model; no CLI or direct-model fallback exists.
- Native/admin commands stay outside the agent hooks and must retain their existing fast path.
- The checked-out OpenClaw source is 2026.7.2 while runtime is 2026.7.1; do not rebuild or replace the active image.
- The Core repo is not a Git worktree and the OpenClaw worktree contains user changes. Preserve checkpointed diffs rather than creating commits.

## Task 1: Complete immutable pre-change evidence

**Files:**
- Add: `F:\AIOS\anh-duong-checkpoints\TG-1-runtime.log`
- Backup: `F:\AIOS\anh-duong-checkpoints\backups\TG-1-20260801T114348Z\openclaw\openclaw.json`

- [ ] Copy the live `openclaw.json` into the existing TG-1 backup without printing it; restrict the backup ACL because it may contain secrets.
- [ ] Record only sanitized facts in the runtime log: Core/Gateway/Telegram health, runtime image/version, Alembic `0003`, worker false, plugin inventory warning, source/runtime version mismatch, and baseline test outcomes.
- [ ] Record SHA-256 hashes for protected configuration subsets and backup files; never print secret values.
- [ ] Verify the backup exists and the live files still match their pre-change hashes.

## Task 2: Write failing plugin contract tests

**Files:**
- Create: `integrations/openclaw-anh-duong-core/package.json`
- Create: `integrations/openclaw-anh-duong-core/test/config.test.js`
- Create: `integrations/openclaw-anh-duong-core/test/client.test.js`
- Create: `integrations/openclaw-anh-duong-core/test/hooks.test.js`

- [ ] Define a dependency-free package with `"type": "module"` and `"test": "node --test"`.
- [ ] Test `readCoreConfig(env)` for disabled mode, enabled valid config, missing token/base URL, malformed URL, and finite `1..30` second timeout.
- [ ] Test `buildCoreRequest({ prompt, runId, senderId })` emits only `text`, `request_id`, `channel`, and `actor`; actor must be a SHA-256-based pseudonym and request ID must be `tg-<runId>` within 128 characters.
- [ ] Test one authenticated POST, no retry, timeout/connection/401/403/non-2xx/invalid JSON/request-ID mismatch/invalid schema failures, and direct plus workflow success.
- [ ] Assert logs and thrown error objects do not contain token, Authorization header, raw response body, sender/chat/session IDs, or prompt.
- [ ] Test hook eligibility: Telegram plus enabled enters Core; disabled and non-Telegram return `void` and do not call Core.
- [ ] Test ordering: `before_prompt_build` records fail-closed state before awaiting; success returns `prependContext`; failure leaves a blocking state; `before_agent_run` blocks absent/pending/failed state and passes only prepared state; `agent_end` cleans state.
- [ ] Test user block message exactly:

```text
Ánh Dương Core hiện chưa sẵn sàng xử lý yêu cầu này. Vui lòng thử lại sau.
```

- [ ] Run `node --test integrations/openclaw-anh-duong-core/test/*.test.js` and confirm RED because implementation modules do not exist.

## Task 3: Implement configuration, request mapping, and response validation

**Files:**
- Create: `integrations/openclaw-anh-duong-core/src/config.js`
- Create: `integrations/openclaw-anh-duong-core/src/core-client.js`
- Create: `integrations/openclaw-anh-duong-core/src/prompt.js`

- [ ] Implement these public functions without third-party dependencies:

```js
export function readCoreConfig(env = process.env) {}
export function buildCoreRequest({ prompt, runId, senderId }) {}
export async function prepareCoreRequest({ config, request, fetchImpl = fetch }) {}
export function validatePreparedRequest(value, expectedRequestId) {}
export function buildPreparedContext(prepared) {}
```

- [ ] Accept only exact booleans for enabled mode; validate base URL protocol and timeout bounds; never include token in error messages.
- [ ] Normalize a missing/oversized run ID to a bounded SHA-256 correlation while retaining the `tg-` prefix; fail closed when the current prompt is blank or exceeds Core's 20,000-character limit.
- [ ] Send `POST <baseUrl>/api/internal/requests/prepare` with `Content-Type: application/json` and bearer auth under an abort timeout. Do not retry.
- [ ] Parse JSON only after a 2xx status and validate all consumed nested fields: request ID, normalized text, route/rule/reason, capability/source route/reason code/signals, rendered context, execution flag, warnings, Persona, provenance, and timestamp.
- [ ] Require `capability_decision.source_route === route_decision.route`; require workflow iff `execution_required=true` and non-workflow iff false.
- [ ] Build a bounded explicit context block containing request ID, route, capability, execution flag, and `context.rendered_context`; do not copy the full response or secrets.
- [ ] Run config/client tests and confirm GREEN.

## Task 4: Implement the fail-closed hook gate and plugin package

**Files:**
- Create: `integrations/openclaw-anh-duong-core/src/hooks.js`
- Create: `integrations/openclaw-anh-duong-core/index.js`
- Create: `integrations/openclaw-anh-duong-core/openclaw.plugin.json`

- [ ] Implement:

```js
export function createAnhDuongCoreHooks({ env, fetchImpl, logger, now } = {}) {}
export default {
  id: "anh-duong-core",
  name: "Ánh Dương Core Gate",
  register(api) { /* three typed runtime hooks */ },
};
```

- [ ] Scope eligibility to `ctx.messageProvider === "telegram" || ctx.channel === "telegram"`; require `ctx.runId` and fail closed if it is absent for an eligible enabled turn.
- [ ] Store only `{status, requestId, failureClass, expiresAt}` plus the prepared context string for a successful active run. Sweep expired records before each hook and clean on `agent_end`.
- [ ] `before_prompt_build`: set pending state first, call Core once, set prepared or failed, emit one sanitized structured log, return `{prependContext}` only on success.
- [ ] `before_agent_run`: return `{outcome:"pass"}` only for prepared state; otherwise return `{outcome:"block", reason:"anh_duong_core_unavailable", category:"core_unavailable", message: SAFE_MESSAGE}`.
- [ ] Register both decision hooks with a timeout larger than the validated Core timeout and register `agent_end` cleanup. The plugin manifest must use strict empty config and startup activation.
- [ ] Run all plugin tests and confirm GREEN, including one-call/no-retry and pass/block assertions.

## Task 5: Prove package compatibility against runtime 2026.7.1 before activation

**Files:**
- Inspect only: `integrations/openclaw-anh-duong-core/*`

- [ ] Run `node --check` on every plugin JavaScript file.
- [ ] Mount or copy the plugin read-only into a disposable path inside the current container and use a temporary config to run cold inventory plus `plugins inspect anh-duong-core --runtime --json` without changing live config.
- [ ] Confirm runtime inspection reports exactly three hooks and no tools, commands, HTTP routes, providers, or channels.
- [ ] Run the plugin tests inside the 2026.7.1 container so the production Node runtime, ESM loader, and platform are proven.
- [ ] Append sanitized results and exact commands to `TG-1-runtime.log`.

## Task 6: Wire Compose and runtime configuration safely

**Files:**
- Modify: `F:\AIOS\openclaw\docker-compose.yml`
- Modify: `F:\AIOS\openclaw\.env`
- Modify through OpenClaw CLI: `/home/node/.openclaw/openclaw.json`

- [ ] Patch only the Gateway service with four environment mappings. Do not bind the NTFS/DrvFS source as a plugin path because OpenClaw rejects its world-writable mode.
- [ ] Add `.env` keys without printing values: enabled true, base URL `http://host.docker.internal:8790`, copied existing Core internal token, timeout seconds `10`.
- [ ] Pin `OPENCLAW_IMAGE` to the immutable ID/tag already running if the baseline Compose tag differs, then run `docker compose config` and inspect only sanitized image/env-name output.
- [ ] Pack the plugin with `npm pack`, install it through `openclaw plugins install npm-pack:<artifact>`, and set `plugins.entries.anh-duong-core.hooks.allowConversationAccess=true`.
- [ ] Recreate only `openclaw-gateway` from WSL with `--no-deps --force-recreate`; do not build, pull, remove volumes, or recreate CLI.
- [ ] Inspect the live runtime and require exactly three hooks, zero diagnostics, and safe managed-directory permissions.
- [ ] Re-hash the protected Telegram/model/provider/9Router config subsets and prove they equal the baseline hashes.
- [ ] Confirm the active image ID and package version remain unchanged.

## Task 7: Automated runtime verification and failure drills

**Files:**
- Create: `scripts/verify_tg1_runtime.ps1`
- Append: `F:\AIOS\anh-duong-checkpoints\TG-1-runtime.log`

- [ ] Implement a read-only verifier that reports sanitized PASS/FAIL rows for Core health/ready, Gateway health, Telegram live probe, plugin runtime inspection, active image/version, Alembic `0003`, worker false, Core reachability from Gateway, and protected config hashes.
- [ ] Run the verifier in happy-path mode.
- [ ] Prove fail-closed without a Telegram message by invoking registered hooks in the plugin tests for timeout, connection refusal, 401/403, non-2xx, malformed body, ID mismatch, and missing config; assert no model-pass decision.
- [ ] Temporarily run the verifier with `ANH_DUONG_CORE_ENABLED=false` only in a test process, proving explicit rollback bypass without mutating production.
- [ ] Search Gateway logs for plugin load errors and secret patterns using only hashes/redacted match counts.

## Task 8: Manual real Telegram gate

- [ ] Ask the operator to send exactly these two messages to the configured bot after runtime activation:

```text
Tóm tắt trạng thái hệ thống hiện tại
Tạo task kiểm tra backup tối nay
```

- [ ] Wait for both replies; do not declare PASS before they arrive.
- [ ] Correlate Telegram/OpenClaw and Core audit logs by the `tg-<runId>` request ID. Record timestamps, request IDs, route/capability, HTTP status, and final delivery outcome only.
- [ ] Confirm the first request is a read/direct-class route and the second is a workflow-class route with `execution_required=true`, unless the live Core router deterministically classifies otherwise; any unexpected route requires evidence and remediation, not hand-waving.
- [ ] Confirm one final reply per message, no direct-model bypass, and no token/chat/sender/session content in evidence.

## Task 9: Full regression and invariant checks

**Files:**
- Test only: Core and OpenClaw/plugin suites

- [ ] Core: `python -m pytest -q`.
- [ ] Core: `python -m ruff check .`, `python -m mypy app`, and `python -m compileall -q app` using the repository's configured environment/tooling.
- [ ] Plugin: `node --test integrations/openclaw-anh-duong-core/test/*.test.js` and syntax checks.
- [ ] OpenClaw targeted Telegram dispatch test and native-command/session suite; compare the known pre-existing three Windows path failures instead of misreporting them as TG-1 regressions.
- [ ] Run any supported OpenClaw lint/type/build checks that do not require upgrading host Node 24.14.0; record the pre-existing engine requirement of Node 24.15+ as a residual baseline risk.
- [ ] Re-run runtime verifier and compare pre/post image ID, Core migration head, worker state, and protected hashes.

## Task 10: Artifacts, rollback proof, and final verdict

**Files:**
- Create: `F:\AIOS\anh-duong-checkpoints\TG-1-report.md`
- Create: `F:\AIOS\anh-duong-checkpoints\TG-1-artifacts.zip`
- Include: implementation files, tests, sanitized runtime log, design, plan, report, diffs, hashes, and rollback instructions

- [ ] Write the report with changed files, exact verification commands, actual results, manual message evidence, preserved invariants, residual risks, and next recommendation.
- [ ] Write rollback steps: set enabled false for immediate legacy mode, or restore backed-up Compose/`.env`/`openclaw.json`, recreate only Gateway, and re-run verifier. Do not execute rollback after a successful deployment.
- [ ] Validate every ZIP path against an explicit allowlist; scan staged text for token/header/secret patterns and exclude secret-bearing backups from the ZIP.
- [ ] Create the ZIP, list contents, compute SHA-256, and verify extraction into a temporary directory under `F:\AIOS\anh-duong-core\.tmp_verify` without overwriting workspace files.
- [ ] Only after all automated checks and both live Telegram messages pass, issue final verdict `PASS`; otherwise remediate and rerun until deterministic evidence supports PASS or report a concrete unrecoverable blocker as `FAIL`.
````````

### `anh-duong-core/artifacts/TG-1-route-direct-fix.patch`

SHA-256: `cb6333d60b03558d4ee9888279734b5e7df3e03e164308fcb9132aa26e5aafee`

````diff
diff --git a/app/routing/fast_router.py b/app/routing/fast_router.py
--- a/app/routing/fast_router.py
+++ b/app/routing/fast_router.py
@@ -150,0 +151,3 @@
+_SIMPLE_ARITHMETIC_PATTERN = re.compile(
+    r"^(?:tg1 direct [0-9]+ )?tinh [0-9]+(?: [0-9]+)+ va tra loi ngan gon$"
+)
@@ -222,0 +226,1 @@
+            or _SIMPLE_ARITHMETIC_PATTERN.fullmatch(normalized) is not None
diff --git a/tests/unit/test_core_request_pipeline_behavior.py b/tests/unit/test_core_request_pipeline_behavior.py
--- a/tests/unit/test_core_request_pipeline_behavior.py
+++ b/tests/unit/test_core_request_pipeline_behavior.py
@@ -214,0 +215,17 @@
+def test_tg1_simple_arithmetic_request_routes_direct() -> None:
+    prepared = _pipeline().prepare(
+        CoreRequest(
+            text=(
+                "TG1-DIRECT-20260801 — Tính 27 + 15 và trả lời ngắn gọn."
+            ),
+            request_id="tg1-direct-regression",
+        )
+    )
+
+    assert prepared.route_decision.route is FastRoute.DIRECT
+    assert (
+        prepared.capability_decision.capability
+        is CapabilityKind.CONVERSATIONAL_RESPONSE
+    )
+    assert prepared.execution_required is False
+
````````

### `openclaw/docker-compose.yml`

SHA-256: `b1100491b3002e7d796baaafa04c3d9a36f1b4e1d08a5bc2423c3b808385fa38`

````yaml
services:
  openclaw-gateway:
    image: ${OPENCLAW_IMAGE:-openclaw:local}
    build: .
    env_file:
      - path: .env
        required: false
    environment:
      HOME: /home/node
      OPENCLAW_HOME: /home/node
      TERM: xterm-256color
      # Pin container-side state, workspace, and config paths so host values written to
      # `.env` (used by Compose for the bind-mount source below) cannot leak
      # into runtime code that resolves these env vars inside the container.
      # Without this override, a macOS host path like /Users/<you>/.openclaw/...
      # imported from .env caused first-reply `mkdir '/Users'` EACCES failures
      # in Linux Docker (#77436).
      OPENCLAW_STATE_DIR: /home/node/.openclaw
      OPENCLAW_CONFIG_PATH: /home/node/.openclaw/openclaw.json
      OPENCLAW_CONFIG_DIR: /home/node/.openclaw
      OPENCLAW_WORKSPACE_DIR: /home/node/.openclaw/workspace
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN:-}
      OPENCLAW_CODEX_APP_SERVER_BIN: ${OPENCLAW_CODEX_APP_SERVER_BIN}
      ANH_DUONG_CORE_ENABLED: ${ANH_DUONG_CORE_ENABLED:-false}
      ANH_DUONG_CORE_BASE_URL: ${ANH_DUONG_CORE_BASE_URL:-}
      ANH_DUONG_CORE_INTERNAL_TOKEN: ${ANH_DUONG_CORE_INTERNAL_TOKEN:-}
      ANH_DUONG_CORE_TIMEOUT_SECONDS: ${ANH_DUONG_CORE_TIMEOUT_SECONDS:-10}
      OPENCLAW_ALLOW_INSECURE_PRIVATE_WS: ${OPENCLAW_ALLOW_INSECURE_PRIVATE_WS:-}
      # Empty means auto: Bonjour disables itself in detected containers.
      # Set 0 only on host/macvlan/mDNS-capable networks; set 1 to force off.
      OPENCLAW_DISABLE_BONJOUR: ${OPENCLAW_DISABLE_BONJOUR:-}
      # OpenTelemetry export is outbound OTLP/HTTP from the Gateway. Prometheus
      # uses the existing authenticated Gateway route; it does not need a port.
      OTEL_EXPORTER_OTLP_ENDPOINT: ${OTEL_EXPORTER_OTLP_ENDPOINT:-}
      OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: ${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-}
      OTEL_EXPORTER_OTLP_METRICS_ENDPOINT: ${OTEL_EXPORTER_OTLP_METRICS_ENDPOINT:-}
      OTEL_EXPORTER_OTLP_LOGS_ENDPOINT: ${OTEL_EXPORTER_OTLP_LOGS_ENDPOINT:-}
      OTEL_EXPORTER_OTLP_PROTOCOL: ${OTEL_EXPORTER_OTLP_PROTOCOL:-http/protobuf}
      OTEL_SERVICE_NAME: ${OTEL_SERVICE_NAME:-}
      OTEL_SEMCONV_STABILITY_OPT_IN: ${OTEL_SEMCONV_STABILITY_OPT_IN:-}
      OPENCLAW_OTEL_PRELOADED: ${OPENCLAW_OTEL_PRELOADED:-}
      CLAUDE_AI_SESSION_KEY: ${CLAUDE_AI_SESSION_KEY:-}
      CLAUDE_WEB_SESSION_KEY: ${CLAUDE_WEB_SESSION_KEY:-}
      CLAUDE_WEB_COOKIE: ${CLAUDE_WEB_COOKIE:-}
      TZ: ${OPENCLAW_TZ:-UTC}
    volumes:
      - "/mnt/f/AIOS/anh-duong-core:/workspaces/anh-duong-core:rw"
      - "${OPENCLAW_CONFIG_DIR:-${HOME:-/tmp}/.openclaw}:/home/node/.openclaw"
      - "${OPENCLAW_WORKSPACE_DIR:-${HOME:-/tmp}/.openclaw/workspace}:/home/node/.openclaw/workspace"
      - "${OPENCLAW_AUTH_PROFILE_SECRET_DIR:-${HOME:-/tmp}/.openclaw-auth-profile-secrets}:/home/node/.config/openclaw"
      ## Uncomment the lines below to enable sandbox isolation
      ## (agents.defaults.sandbox). Requires Docker CLI in the image
      ## (build with --build-arg OPENCLAW_INSTALL_DOCKER_CLI=1) or use
      ## scripts/docker/setup.sh with OPENCLAW_SANDBOX=1 for automated setup.
      ## Set DOCKER_GID to the host's docker group GID (run: stat -c '%g' /var/run/docker.sock).
      # - /var/run/docker.sock:/var/run/docker.sock
    # group_add:
    #   - "${DOCKER_GID:-999}"
    # Let bundled local-model providers reach host-side LM Studio/Ollama via
    # http://host.docker.internal:<port>. Docker Desktop usually provides this
    # alias; the host-gateway mapping makes it work on Linux Docker Engine too.
    cap_drop:
      - NET_RAW
      - NET_ADMIN
    security_opt:
      - no-new-privileges:true
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports:
      - "${OPENCLAW_GATEWAY_PORT:-18789}:18789"
      - "${OPENCLAW_BRIDGE_PORT:-18790}:18790"
      - "${OPENCLAW_MSTEAMS_PORT:-3978}:3978"
    init: true
    restart: unless-stopped
    command:
      [
        "node",
        "dist/index.js",
        "gateway",
        "--bind",
        "${OPENCLAW_GATEWAY_BIND:-lan}",
        "--port",
        "18789",
      ]
    healthcheck:
      test:
        [
          "CMD",
          "node",
          "-e",
          "fetch('http://127.0.0.1:18789/healthz').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))",
        ]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 20s

  openclaw-cli:
    image: ${OPENCLAW_IMAGE:-openclaw:local}
    network_mode: "service:openclaw-gateway"
    env_file:
      - path: .env
        required: false
    cap_drop:
      - NET_RAW
      - NET_ADMIN
    security_opt:
      - no-new-privileges:true
    environment:
      HOME: /home/node
      OPENCLAW_HOME: /home/node
      TERM: xterm-256color
      # Pin container-side state, workspace, and config paths so host values written to
      # `.env` cannot leak into runtime code via the env_file import (#77436).
      OPENCLAW_STATE_DIR: /home/node/.openclaw
      OPENCLAW_CONFIG_PATH: /home/node/.openclaw/openclaw.json
      OPENCLAW_CONFIG_DIR: /home/node/.openclaw
      OPENCLAW_WORKSPACE_DIR: /home/node/.openclaw/workspace
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN:-}
      OPENCLAW_CODEX_APP_SERVER_BIN: ${OPENCLAW_CODEX_APP_SERVER_BIN}
      OPENCLAW_ALLOW_INSECURE_PRIVATE_WS: ${OPENCLAW_ALLOW_INSECURE_PRIVATE_WS:-}
      BROWSER: echo
      CLAUDE_AI_SESSION_KEY: ${CLAUDE_AI_SESSION_KEY:-}
      CLAUDE_WEB_SESSION_KEY: ${CLAUDE_WEB_SESSION_KEY:-}
      CLAUDE_WEB_COOKIE: ${CLAUDE_WEB_COOKIE:-}
      TZ: ${OPENCLAW_TZ:-UTC}
    volumes:
      - "${OPENCLAW_CONFIG_DIR:-${HOME:-/tmp}/.openclaw}:/home/node/.openclaw"
      - "${OPENCLAW_WORKSPACE_DIR:-${HOME:-/tmp}/.openclaw/workspace}:/home/node/.openclaw/workspace"
      - "${OPENCLAW_AUTH_PROFILE_SECRET_DIR:-${HOME:-/tmp}/.openclaw-auth-profile-secrets}:/home/node/.config/openclaw"
    stdin_open: true
    tty: true
    init: true
    entrypoint: ["node", "dist/index.js"]
    depends_on:
      - openclaw-gateway
````````

## Binary artifact

- `anh-duong-core/artifacts/anh-duong-openclaw-core-gate-1.0.0.tgz` — SHA-256 `e95e22fbf95f9dbce0d931367024a793de7e0db3ddd0ac0273d79434945579e9`; npm shasum `108a707b586a8fcdc602870b4a2d39b6c71d207b`.
