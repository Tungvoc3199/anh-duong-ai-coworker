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
    ProjectResolutionFailed,
    TaskContextNotFound,
    TaskProjectMismatch,
)
from app.persona import PersonaSnapshot
from app.policy import DecisionKind, RiskLevel
from app.privacy import telegram_idempotency_key
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

    def list(
        self,
        *,
        status: ProjectStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Project]:
        projects = list(self.projects.values())
        if status is not None:
            projects = [project for project in projects if project.status is status]
        return projects[offset : offset + limit]


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
    assert prepared.capability_decision.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
    assert prepared.execution_required is False
    assert prepared.workflow is None
    assert prepared.created_at == NOW


def test_workflow_context_includes_effective_runtime_policy() -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(
            text=(
                "Research trang Facebook công khai của dự án, đọc và tóm "
                "tắt nội dung. Nếu cần publish ra ngoài thì dừng lại xin "
                "approval sau khi xong phần đọc web an toàn."
            ),
            request_id="facebook-policy-context",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-facebook-policy-context",
        )
    )

    assert prepared.workflow is not None
    context = prepared.context.rendered_context
    assert "Runtime Policy:" in context
    assert "- safe_without_approval: web_search_read" in context
    assert "- step_gate: destructive" in context
    assert "complete_safe_steps_before_approval_gate" in context


def test_workflow_context_uses_effective_policy_for_approval_task() -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(
            text="Deploy bản này",
            request_id="deploy-policy-context",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-deploy-policy-context",
        )
    )

    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True
    context = prepared.context.rendered_context
    assert "Runtime Policy:" in context
    assert "- effective_risk_level: 0" in context
    assert "- approval_required: true" in context
    assert "- policy_rule_id: action.unknown" in context
    assert "- policy_decision: escalate" in context


@pytest.mark.parametrize(
    "text",
    [
        "alo",
        "Hôm nay em thấy thế nào?",
    ],
)
def test_dr1_casual_conversation_does_not_create_workflow(text: str) -> None:
    prepared = _pipeline(
        project_reader=ProjectReader((_project(),)),
    ).prepare(CoreRequest(text=text))

    assert prepared.route_decision.route is FastRoute.DIRECT
    assert prepared.capability_decision.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
    assert prepared.execution_required is False
    assert prepared.workflow is None


def test_tg1_simple_arithmetic_request_routes_direct() -> None:
    prepared = _pipeline().prepare(
        CoreRequest(
            text=("TG1-DIRECT-20260801 — Tính 27 + 15 và trả lời ngắn gọn."),
            request_id="tg1-direct-regression",
        )
    )

    assert prepared.route_decision.route is FastRoute.DIRECT
    assert prepared.capability_decision.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
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


def test_dr1_preserves_risk_zero_telegram_workflow_route() -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(
            text=(
                "WR1-RISK0-20260801T120000Z — Soạn checklist 5 bước "
                "kiểm tra trạng thái Ánh Dương Core theo chế độ chỉ đọc. "
                "Không chạy lệnh, không sửa file, không sửa cấu hình và "
                "không restart dịch vụ."
            ),
            request_id="tg-run-risk0",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-99",
        )
    )

    assert prepared.route_decision.route is FastRoute.WORKFLOW
    assert prepared.execution_required is True
    assert prepared.project_id == project.id
    assert prepared.workflow is not None
    assert prepared.workflow.project_id == project.id
    assert prepared.workflow.goal == prepared.normalized_text
    assert prepared.workflow.mode == "quick"
    assert prepared.workflow.priority == "high"
    assert prepared.workflow.risk_level is RiskLevel.READ_ONLY
    assert prepared.workflow.approval_required is False
    assert prepared.workflow.workspace == project.path_wsl
    assert prepared.workflow.requested_by == "telegram:actor-hash"
    assert prepared.workflow.source_channel == "telegram"
    assert prepared.workflow.source_chat_id == "chat-42"
    assert prepared.workflow.source_session_id == "session-42"
    assert prepared.workflow.idempotency_key == telegram_idempotency_key(
        source_chat_id="chat-42",
        source_message_id="message-99",
    )
    assert prepared.workflow.correlation_id == "tg-run-risk0"
    assert prepared.workflow.policy_decision is DecisionKind.ALLOW
    assert prepared.workflow.policy_rule_id == "risk.read_only.allow"
    assert "No schema changes" in prepared.workflow.constraints
    assert "no_service_restart" in prepared.workflow.constraints


def test_dr1r_exact_telegram_gate_is_risk_zero_without_approval() -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(
            text=(
                "Đọc file README.md của dự án Ánh Dương Core và trả lời "
                "đúng mã DR1R-CODEX-TEST; chỉ đọc, không sửa file và "
                "không thực hiện side effect."
            ),
            request_id="dr1r-exact-telegram-gate",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-dr1r-exact",
        )
    )

    assert prepared.route_decision.route is FastRoute.WORKFLOW
    assert prepared.capability_decision.capability is not CapabilityKind.UNKNOWN_WORKFLOW
    assert prepared.execution_required is True
    assert prepared.workflow is not None
    assert prepared.workflow.risk_level is RiskLevel.READ_ONLY
    assert prepared.workflow.approval_required is False
    assert prepared.workflow.policy_decision is DecisionKind.ALLOW
    assert prepared.workflow.policy_rule_id == "risk.read_only.allow"


def test_read_only_health_ready_workflow_is_allowed_without_approval() -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(
            text=(
                "Thực hiện một workflow read-only: kiểm tra trạng thái "
                "/health và /ready của Ánh Dương Core, không sửa file, "
                "không restart service, không thay đổi cấu hình, rồi báo "
                "lại kết quả cho anh."
            ),
            request_id="tg-readonly-health-ready",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-readonly-health-ready",
        )
    )

    assert prepared.route_decision.route is FastRoute.WORKFLOW
    assert prepared.execution_required is True
    assert prepared.workflow is not None
    assert prepared.workflow.risk_level is RiskLevel.READ_ONLY
    assert prepared.workflow.approval_required is False
    assert prepared.workflow.policy_decision is DecisionKind.ALLOW
    assert prepared.workflow.policy_rule_id == "risk.read_only.allow"
    assert "no_service_restart" in prepared.workflow.constraints


@pytest.mark.parametrize(
    "text",
    [
        "E đưa ra chỉ dẫn để a sửa nào",
        "Hướng dẫn anh sửa lỗi này",
        "Cho anh lệnh để sửa",
        "Lỗi này sửa thế nào",
        "Em nghĩ nên sửa như nào",
        "Phân tích và nói anh cách sửa",
        "Tại sao lỗi này xảy ra",
        "Nên làm gì tiếp theo",
        "Hướng dẫn anh chạy test",
        "Cho anh biết cách tạo file report.md",
        "Hướng dẫn anh restart service",
        "Cho anh lệnh deploy để anh tự chạy",
    ],
)
def test_advisory_action_mentions_do_not_create_workflow(text: str) -> None:
    prepared = _pipeline(
        project_reader=ProjectReader((_project(),)),
    ).prepare(
        CoreRequest(
            text=text,
            request_id="advisory-direct",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-advisory-direct",
        )
    )

    assert prepared.route_decision.route is FastRoute.DIRECT
    assert prepared.route_decision.rule_id == "routing.direct.advisory_action_mention"
    assert prepared.capability_decision.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
    assert prepared.execution_required is False
    assert prepared.workflow is None
    assert prepared.project_id is None


@pytest.mark.parametrize(
    "text",
    [
        "Hướng dẫn anh tạo workflow",
        "Workflow này chạy test như nào",
    ],
)
def test_advisory_workflow_mentions_do_not_create_workflow(text: str) -> None:
    prepared = _pipeline(
        project_reader=ProjectReader((_project(),)),
    ).prepare(CoreRequest(text=text, request_id="advisory-workflow-direct"))

    assert prepared.route_decision.route is FastRoute.DIRECT
    assert prepared.route_decision.rule_id == "routing.direct.advisory_action_mention"
    assert prepared.capability_decision.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
    assert prepared.execution_required is False
    assert prepared.workflow is None


@pytest.mark.parametrize(
    "text",
    [
        "Em sửa lỗi này đi",
        "Sửa worker.py cho anh",
        "Chạy test đi",
        "Tạo file report.md",
        "Restart service",
        "Deploy bản này",
        "Xóa file tạm đi",
        "Commit thay đổi này",
        "Gửi báo cáo này đi",
        "Chạy lệnh ls đi",
    ],
)
def test_explicit_execution_requests_create_workflow(text: str) -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(CoreRequest(text=text, request_id="execution-workflow"))

    assert prepared.route_decision.route is FastRoute.WORKFLOW
    assert prepared.execution_required is True
    assert prepared.workflow is not None


@pytest.mark.parametrize(
    "text",
    [
        "Hướng dẫn anh chạy test, rồi chạy test đi",
        "Cho anh lệnh deploy, rồi deploy bản này",
        "Hướng dẫn anh chạy test, sau đó chạy test đi",
    ],
)
def test_mixed_advisory_then_execution_creates_workflow(text: str) -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(CoreRequest(text=text, request_id="mixed-execution-workflow"))

    assert prepared.route_decision.route is FastRoute.WORKFLOW
    assert prepared.execution_required is True
    assert prepared.workflow is not None


def test_unknown_non_action_uses_direct_conversation_without_workflow() -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(
            text="Màu tím.",
            request_id="tg-run-unknown",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-100",
        )
    )

    assert prepared.route_decision.route is FastRoute.DIRECT
    assert prepared.capability_decision.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
    assert prepared.execution_required is False
    assert prepared.workflow is None
    assert prepared.project_id is None


def test_workflow_without_deterministic_project_fails_closed() -> None:
    request = CoreRequest(
        text="Chạy pytest cho app.",
        channel="telegram",
        source_chat_id="chat-42",
        source_message_id="message-101",
    )

    with pytest.raises(ProjectResolutionFailed, match="exactly one active project"):
        _pipeline().prepare(request)

    with pytest.raises(ProjectResolutionFailed, match="exactly one active project"):
        _pipeline(
            project_reader=ProjectReader((_project("proj_one"), _project("proj_two"))),
        ).prepare(request)


def test_missing_project_and_task_raise_clear_pipeline_errors() -> None:
    pipeline = _pipeline()

    with pytest.raises(ProjectContextNotFound, match="proj_missing"):
        pipeline.prepare(CoreRequest(text="Xem Project missing.", project_id="proj_missing"))
    with pytest.raises(TaskContextNotFound, match="task_missing"):
        pipeline.prepare(CoreRequest(text="Xem Task missing.", task_id="task_missing"))


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
    prepared = _pipeline(retriever=FailingRetriever()).prepare(CoreRequest(text="Xin chào!"))

    assert prepared.warnings == ("memory_retrieval_failed: MemoryRepositoryError",)
    assert prepared.warnings == prepared.context.warnings
    assert prepared.context.estimated_tokens <= (
        prepared.context.token_budget.usable_context_tokens
    )
    assert prepared.provenance.route_rule_id == prepared.route_decision.rule_id
    assert prepared.provenance.capability_reason_code == prepared.capability_decision.reason_code
    assert "request:current" in prepared.provenance.context_source_refs


def test_secret_is_redacted_from_all_prepared_response_text() -> None:
    secret = "WR1_TEST_SECRET_MARKER"

    prepared = _pipeline(
        project_reader=ProjectReader((_project(),)),
    ).prepare(CoreRequest(text=f"Ghi nhớ api_key={secret}"))

    serialized = str(prepared.model_dump(mode="json"))
    assert secret not in serialized
    assert "api_key=[REDACTED]" in prepared.normalized_text


def test_success_writes_one_minimal_audit_event() -> None:
    writer = RecordingAuditWriter()

    prepared = _pipeline(
        audit_writer=writer,
        project_reader=ProjectReader((_project(),)),
    ).prepare(
        CoreRequest(
            text="Xin chào! api_key=WR1_TEST_SECRET_MARKER",
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
        "route": "direct",
        "capability": "conversational_response",
        "persona_version": "1.7",
        "persona_content_hash": "b" * 64,
        "token_estimate": prepared.context.estimated_tokens,
        "warning_count": 0,
    }
    assert "sk-proj" not in str(event.model_dump(mode="json"))


def test_context_bundle_preserves_required_section_order() -> None:
    prepared = _pipeline().prepare(CoreRequest(text="Xin chào!"))

    assert tuple(section.kind for section in prepared.context.sections) == tuple(ContextSectionKind)


def test_natural_vietnamese_readonly_health_ready_preserves_safety() -> None:
    project = _project()
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(
            text=(
                "Kiểm tra giúp anh trạng thái hiện tại của Ánh Dương Core. "
                "Nếu hệ thống đang ổn thì báo ngắn gọn health, ready và kết "
                "luận có thể tiếp tục làm việc hay không. Chỉ kiểm tra "
                "read-only, không sửa file, không restart service, không đổi "
                "cấu hình."
            ),
            request_id="tg-natural-readonly-health-ready",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-natural-readonly-health-ready",
        )
    )

    assert prepared.route_decision.route is FastRoute.WORKFLOW
    assert prepared.workflow is not None
    assert prepared.workflow.mode == "quick"
    assert prepared.workflow.risk_level is RiskLevel.READ_ONLY
    assert prepared.workflow.approval_required is False
    assert prepared.workflow.policy_decision is DecisionKind.ALLOW
    assert "read_only" in prepared.workflow.constraints
    assert "no_file_changes" in prepared.workflow.constraints
    assert "no_config_changes" in prepared.workflow.constraints
    assert "no_service_restart" in prepared.workflow.constraints
    assert "no_commands" not in prepared.workflow.constraints


def test_bug_tg_intent_routing_exact_multiline_readonly_is_risk_zero() -> None:
    project = _project()
    text = (
        "Kiểm tra trạng thái hệ thống hiện tại bằng chế độ chỉ đọc.\n\n"
        "Yêu cầu:\n"
        "Core tự kiểm tra /health và /ready.\n"
        "Không gọi OpenClaw hoặc model.\n"
        "Không chạy Git.\n"
        "Không sửa file hoặc config.\n"
        "Không restart service.\n"
        "Không install, deploy hoặc thay đổi hệ thống.\n"
        "Chỉ trả về kết quả health/ready thực tế và kết luận hệ thống có "
        "đang sẵn sàng hay không."
    )
    prepared = _pipeline(
        project_reader=ProjectReader((project,)),
    ).prepare(
        CoreRequest(
            text=text,
            request_id="ad-bug-tg-intent-routing-2-readonly",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-ad-bug-readonly",
        )
    )

    assert prepared.route_decision.route is FastRoute.WORKFLOW
    assert prepared.execution_required is True
    assert prepared.workflow is not None
    assert prepared.workflow.mode == "quick"
    assert prepared.workflow.risk_level is RiskLevel.READ_ONLY
    assert prepared.workflow.approval_required is False
    assert prepared.workflow.policy_decision is DecisionKind.ALLOW
    assert prepared.workflow.policy_rule_id == "risk.read_only.allow"
    assert {
        "read_only",
        "no_file_changes",
        "no_config_changes",
        "no_service_restart",
        "no_git",
        "no_openclaw",
        "no_model",
        "no_package_install",
        "no_deploy",
        "no_system_mutation",
    }.issubset(set(prepared.workflow.constraints))


def test_question_mark_follow_up_does_not_create_execution_workflow() -> None:
    prepared = _pipeline(
        project_reader=ProjectReader((_project(),)),
    ).prepare(
        CoreRequest(
            text="?",
            request_id="ad-bug-tg-intent-routing-2-follow-up",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-ad-bug-follow-up",
        )
    )

    assert prepared.route_decision.route is FastRoute.DIRECT
    assert prepared.capability_decision.capability is CapabilityKind.CONVERSATIONAL_RESPONSE
    assert prepared.execution_required is False
    assert prepared.workflow is None
    assert prepared.project_id is None


def test_exact_user_readonly_system_check_never_requires_owner_approval() -> None:
    project = _project()
    text = (
        "Dương, kiểm tra tình trạng hệ thống Ánh Dương hiện tại giúp anh.\n\n"
        "Yêu cầu:\n"
        "- kiểm tra Core service;\n"
        "- kiểm tra /health và /ready;\n"
        "- kiểm tra database quick_check;\n"
        "- chỉ đọc, không sửa hay restart gì;\n"
        "- chỉ báo thành công khi có bằng chứng kiểm tra thật."
    )
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id="ad-bug-tg-readonly-intent-1",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-readonly-intent-1",
        )
    )

    assert prepared.route_decision.route is FastRoute.WORKFLOW
    assert prepared.workflow is not None
    assert prepared.workflow.mode == "quick"
    assert prepared.workflow.risk_level is RiskLevel.READ_ONLY
    assert prepared.workflow.approval_required is False
    assert prepared.workflow.policy_decision is DecisionKind.ALLOW
    assert prepared.workflow.policy_rule_id == "risk.read_only.allow"
    assert "read_only" in prepared.workflow.constraints
    assert "no_file_changes" in prepared.workflow.constraints
    assert "no_config_changes" in prepared.workflow.constraints
    assert "no_service_restart" in prepared.workflow.constraints
    assert "no_system_mutation" in prepared.workflow.constraints


def test_mixed_readonly_and_mutation_never_uses_readonly_fast_path() -> None:
    project = _project()
    text = (
        "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
        "không restart service, nhưng sửa config nếu lỗi."
    )
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id="ad-bug-tg-readonly-mixed-mutation",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-readonly-mixed-mutation",
        )
    )

    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True
    assert prepared.workflow.policy_decision is not DecisionKind.ALLOW


@pytest.mark.parametrize(
    "suffix",
    [
        "nhưng deploy bản mới",
        "nhưng restart nếu lỗi",
        "nhưng install package nếu lỗi",
        "hãy sửa config nếu lỗi",
    ],
)
def test_mixed_readonly_status_and_positive_side_effect_requires_approval(suffix: str) -> None:
    project = _project()
    text = (
        "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
        f"không restart service, {suffix}."
    )
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id=f"mixed-side-effect-{suffix}",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id=f"message-{suffix}",
        )
    )
    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True


def test_generic_gateway_readonly_health_check_remains_approval_free() -> None:
    project = _project()
    text = (
        "Kiểm tra trạng thái Gateway health và ready bằng chế độ chỉ đọc, "
        "không sửa file, không sửa config, không restart service."
    )
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id="generic-gateway-readonly-health",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="message-gateway-readonly-health",
        )
    )
    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is False
    assert prepared.workflow.policy_decision is DecisionKind.ALLOW
    assert prepared.workflow.policy_rule_id == "risk.read_only.allow"


@pytest.mark.parametrize(
    "text",
    [
        (
            "Dương, kiểm tra tình trạng hệ thống Ánh Dương hiện tại giúp anh. "
            "Kiểm tra Core service, health, ready và database quick_check; "
            "chỉ đọc, không sửa hay restart gì."
        ),
        (
            "Xác minh trạng thái Ánh Dương Core: health và ready. "
            "Chỉ đọc, không thay đổi gì, không khởi động lại dịch vụ."
        ),
        (
            "Xem giúp anh status Ánh Dương Core, health/ready hiện có ổn không. "
            "Chỉ xem thôi, không sửa gì và không restart service."
        ),
        ("Check status Anh Duong Core health/ready. Read only, no changes and no restart."),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready bằng chế độ chỉ đọc. "
            "Không install, deploy hoặc thay đổi hệ thống. Gửi kết quả cho anh."
        ),
    ],
)
def test_readonly_core_status_paraphrase_matrix_is_approval_free(text: str) -> None:
    project = _project()
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id=f"safe-matrix-{abs(hash(text))}",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id=f"safe-message-{abs(hash(text))}",
        )
    )

    assert prepared.execution_required is True
    assert prepared.workflow is not None
    assert prepared.workflow.risk_level is RiskLevel.READ_ONLY
    assert prepared.workflow.approval_required is False
    assert prepared.workflow.policy_decision is DecisionKind.ALLOW
    assert prepared.workflow.policy_rule_id == "risk.read_only.allow"


@pytest.mark.parametrize(
    "text",
    [
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, sửa config nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service và sửa config nếu lỗi."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, rồi deploy bản mới."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service. Deploy bản mới nếu lỗi."
        ),
        (
            "Check status Anh Duong Core health/ready, read only, "
            "no restart, then install package if unhealthy."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không restart service, gửi email cho admin nếu lỗi."
        ),
    ],
)
def test_readonly_core_status_adversarial_matrix_never_bypasses_policy(text: str) -> None:
    project = _project()
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id=f"unsafe-matrix-{abs(hash(text))}",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id=f"unsafe-message-{abs(hash(text))}",
        )
    )

    assert prepared.execution_required is True
    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True
    assert prepared.workflow.policy_decision is not DecisionKind.ALLOW


@pytest.mark.parametrize(
    "text",
    [
        ("Chỉ đọc, không sửa file hay config gì, nhưng deploy bản mới nếu health không ổn."),
        ("Chỉ đọc, không sửa file hay config gì, nhưng restart service nếu ready lỗi."),
    ],
)
def test_legacy_readonly_fallback_never_allows_unnegated_mutation(text: str) -> None:
    project = _project()
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id=f"legacy-mixed-{abs(hash(text))}",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id=f"legacy-mixed-message-{abs(hash(text))}",
        )
    )

    assert prepared.execution_required is True
    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True
    assert prepared.workflow.policy_decision is not DecisionKind.ALLOW


@pytest.mark.parametrize(
    "text",
    [
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready, chỉ đọc, "
            "không sửa gì và nếu lỗi deploy bản mới."
        ),
        (
            "Check status Anh Duong Core health/ready, read only, "
            "no changes and if unhealthy install package."
        ),
    ],
)
def test_conditional_mutation_without_then_never_gets_readonly_policy(text: str) -> None:
    project = _project()
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id=f"conditional-no-then-{abs(hash(text))}",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id=f"conditional-no-then-message-{abs(hash(text))}",
        )
    )

    assert prepared.execution_required is True
    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True
    assert prepared.workflow.policy_decision is not DecisionKind.ALLOW


@pytest.mark.parametrize(
    "effect",
    [
        "stop service nếu lỗi",
        "disable service nếu lỗi",
        "reload service nếu lỗi",
        "shutdown máy nếu lỗi",
        "dừng service nếu lỗi",
        "tắt service nếu lỗi",
    ],
)
def test_generic_status_with_service_lifecycle_effect_requires_policy_gate(effect: str) -> None:
    project = _project()
    text = f"Kiểm tra trạng thái Gateway health/ready, chỉ đọc, không sửa gì, nhưng {effect}."
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id=f"service-lifecycle-{abs(hash(effect))}",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id=f"service-lifecycle-message-{abs(hash(effect))}",
        )
    )

    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True
    assert prepared.workflow.policy_decision is not DecisionKind.ALLOW


@pytest.mark.parametrize(
    "text",
    [
        (
            "Check status Anh Duong Core health/ready. Read only, no changes "
            "and no restart. Then rotate credentials."
        ),
        (
            "Kiểm tra tình trạng Ánh Dương Core health/ready. Chỉ đọc, "
            "không sửa gì, rồi format disk nếu lỗi."
        ),
        (
            "Xác minh trạng thái Ánh Dương Core health/ready. Chỉ đọc, "
            "không thay đổi gì. Then remove the database."
        ),
    ],
)
def test_unknown_post_readonly_action_never_bypasses_pipeline_policy(text: str) -> None:
    project = _project()
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id=f"unknown-post-readonly-{abs(hash(text))}",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id=f"unknown-post-readonly-message-{abs(hash(text))}",
        )
    )

    assert prepared.execution_required is True
    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True
    assert prepared.workflow.policy_decision is not DecisionKind.ALLOW


def test_harmless_readonly_report_clause_stays_approval_free() -> None:
    project = _project()
    text = (
        "Kiểm tra tình trạng Ánh Dương Core health/ready. Chỉ đọc, "
        "không sửa gì và không restart service. Gửi kết quả và bằng chứng cho anh."
    )
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id="harmless-readonly-report",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="harmless-readonly-report-message",
        )
    )

    assert prepared.workflow is not None
    assert prepared.workflow.risk_level is RiskLevel.READ_ONLY
    assert prepared.workflow.approval_required is False
    assert prepared.workflow.policy_decision is DecisionKind.ALLOW


@pytest.mark.parametrize(
    "text",
    [
        (
            "Check status Anh Duong Core health/ready. "
            "Read only, no changes except deploy if unhealthy, no restart."
        ),
        (
            "Rotate credentials, then check status Anh Duong Core health/ready. "
            "Read only, no changes and no restart."
        ),
    ],
)
def test_readonly_mixed_action_on_either_side_never_bypasses_policy(text: str) -> None:
    project = _project()
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id=f"readonly-bidirectional-{abs(hash(text))}",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id=f"readonly-bidirectional-message-{abs(hash(text))}",
        )
    )

    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True
    assert prepared.workflow.policy_decision is not DecisionKind.ALLOW


def test_legacy_readonly_unknown_action_never_gets_allow() -> None:
    project = _project()
    text = (
        "Read only. No commands, no file changes, no config changes, no restart. "
        "Rotate credentials."
    )
    prepared = _pipeline(project_reader=ProjectReader((project,))).prepare(
        CoreRequest(
            text=text,
            request_id="legacy-readonly-unknown-action",
            channel="telegram",
            actor="telegram:actor-hash",
            source_chat_id="chat-42",
            source_session_id="session-42",
            source_message_id="legacy-readonly-unknown-action-message",
        )
    )
    assert prepared.workflow is not None
    assert prepared.workflow.approval_required is True
    assert prepared.workflow.policy_decision is not DecisionKind.ALLOW
