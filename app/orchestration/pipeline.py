from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import uuid4

from app.audit import AuditEvent, SecretRedactor
from app.capabilities import CapabilityRouter
from app.context_builder import (
    ContextBuilder,
    ContextBuildRequest,
    ProjectContextSnapshot,
    RuntimePolicySnapshot,
    TaskContextSnapshot,
)
from app.orchestration.errors import (
    ProjectContextNotFound,
    ProjectResolutionFailed,
    TaskContextNotFound,
    TaskProjectMismatch,
)
from app.orchestration.models import (
    AttachmentFact,
    CoreRequest,
    PersonaReference,
    PreparedRequest,
    RequestProvenance,
)
from app.orchestration.workflow import WorkflowResolver
from app.persona import PersonaSnapshot
from app.projects import Project, ProjectNotFound, ProjectStatus
from app.routing import FastRoute, FastRouter
from app.tasks import Task, TaskNotFound, TaskStatus


class ProjectReader(Protocol):
    def get(self, project_id: str) -> Project: ...

    def list(
        self,
        *,
        status: ProjectStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Project]: ...


class TaskReader(Protocol):
    def get(self, task_id: str) -> Task: ...


class AuditEventWriter(Protocol):
    def write(self, event: AuditEvent) -> None: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


class CoreRequestPipeline:
    """Prepare one Core request without executing the selected capability."""

    def __init__(
        self,
        *,
        persona_loader: Callable[[], PersonaSnapshot],
        fast_router: FastRouter,
        capability_router: CapabilityRouter,
        context_builder: ContextBuilder,
        project_reader: ProjectReader,
        task_reader: TaskReader,
        audit_writer: AuditEventWriter,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_request_id,
        redactor: SecretRedactor | None = None,
        workflow_resolver: WorkflowResolver | None = None,
    ) -> None:
        self._persona_loader = persona_loader
        self._fast_router = fast_router
        self._capability_router = capability_router
        self._context_builder = context_builder
        self._project_reader = project_reader
        self._task_reader = task_reader
        self._audit_writer = audit_writer
        self._clock = clock
        self._id_factory = id_factory
        self._redactor = redactor or SecretRedactor()
        self._workflow_resolver = workflow_resolver or WorkflowResolver()

    def prepare(self, request: CoreRequest) -> PreparedRequest:
        persona = self._persona_loader()
        route_decision = self._fast_router.route(
            request.text,
            attachments=request.attachments,
        )
        capability_decision = self._capability_router.route(
            route_decision,
            request.text,
        )

        task = self._load_task(request.task_id)
        project = self._resolve_project(
            request,
            task,
            workflow=route_decision.route is FastRoute.WORKFLOW,
        )
        self._validate_task_project(request, task)

        request_id = request.request_id or self._id_factory()
        normalized_text = self._redacted_text(request.text)
        workflow = (
            self._workflow_resolver.resolve(
                request=request,
                request_id=request_id,
                normalized_text=normalized_text,
                capability=capability_decision.capability,
                project=project,
            )
            if route_decision.route is FastRoute.WORKFLOW
            and project is not None
            else None
        )

        context = self._context_builder.build(
            ContextBuildRequest(
                current_request=request.text,
                persona=persona,
                fast_router_decision=route_decision,
                capability_decision=capability_decision,
                project_context=(
                    self._project_snapshot(project)
                    if project is not None
                    else None
                ),
                task_context=(
                    self._task_snapshot(task) if task is not None else None
                ),
                runtime_policy=(
                    RuntimePolicySnapshot(
                        risk_level=workflow.risk_level,
                        approval_required=workflow.approval_required,
                        policy_decision=workflow.policy_decision,
                        policy_rule_id=workflow.policy_rule_id,
                        policy_reason=workflow.policy_reason,
                    )
                    if workflow is not None
                    else None
                ),
                memory_scope_id=request.memory_scope_id,
                attachment_context=self._attachment_context(request.attachments),
            )
        )
        context_source_refs = tuple(
            source_ref
            for item in context.provenance
            for source_ref in item.source_refs
        )
        prepared = PreparedRequest(
            request_id=request_id,
            normalized_text=normalized_text,
            persona=PersonaReference(
                version=persona.version,
                content_hash=persona.content_hash,
            ),
            route_decision=route_decision,
            capability_decision=capability_decision,
            context=context,
            project_id=project.id if project is not None else request.project_id,
            task_id=request.task_id,
            execution_required=route_decision.route is FastRoute.WORKFLOW,
            workflow=workflow,
            warnings=context.warnings,
            provenance=RequestProvenance(
                persona_version=persona.version,
                persona_content_hash=persona.content_hash,
                route_rule_id=route_decision.rule_id,
                capability_reason_code=capability_decision.reason_code,
                project_version=project.version if project is not None else None,
                task_version=task.version if task is not None else None,
                context_source_refs=context_source_refs,
            ),
            created_at=self._clock(),
        )
        self._write_audit(prepared, request)
        return prepared

    def _load_project(self, project_id: str | None) -> Project | None:
        if project_id is None:
            return None
        try:
            return self._project_reader.get(project_id)
        except ProjectNotFound as error:
            raise ProjectContextNotFound(project_id) from error

    def _resolve_project(
        self,
        request: CoreRequest,
        task: Task | None,
        *,
        workflow: bool,
    ) -> Project | None:
        if request.project_id is not None:
            return self._load_project(request.project_id)
        if not workflow:
            return None
        if task is not None:
            return self._load_project(task.project_id)
        active = self._project_reader.list(
            status=ProjectStatus.ACTIVE,
            limit=2,
        )
        if len(active) != 1:
            raise ProjectResolutionFailed()
        return active[0]

    def _load_task(self, task_id: str | None) -> Task | None:
        if task_id is None:
            return None
        try:
            return self._task_reader.get(task_id)
        except TaskNotFound as error:
            raise TaskContextNotFound(task_id) from error

    @staticmethod
    def _validate_task_project(request: CoreRequest, task: Task | None) -> None:
        if (
            task is not None
            and request.project_id is not None
            and task.project_id != request.project_id
        ):
            raise TaskProjectMismatch(
                task_id=task.id,
                task_project_id=task.project_id,
                requested_project_id=request.project_id,
            )

    @classmethod
    def _project_snapshot(cls, project: Project) -> ProjectContextSnapshot:
        return ProjectContextSnapshot(
            identity=project.id,
            goal=project.summary,
            current_phase=project.current_phase,
            architecture_constraints=tuple(
                cls._stringify_fact(item) for item in project.constraints
            ),
            status=project.status.value,
        )

    @staticmethod
    def _task_snapshot(task: Task) -> TaskContextSnapshot:
        active_goal = task.title
        if task.description:
            active_goal = f"{task.title}: {task.description}"
        blockers = (
            (task.result_summary,)
            if task.status is TaskStatus.BLOCKED and task.result_summary
            else ()
        )
        history = (task.result_summary,) if task.result_summary else ()
        return TaskContextSnapshot(
            identity=task.id,
            active_goal=active_goal,
            status=task.status.value,
            blockers=blockers,
            next_action=task.current_step_id,
            history=history,
        )

    @staticmethod
    def _stringify_fact(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def _attachment_context(
        self,
        attachments: tuple[AttachmentFact, ...],
    ) -> tuple[str, ...]:
        return tuple(self._attachment_line(item) for item in attachments)

    def _attachment_line(self, item: AttachmentFact) -> str:
        parts = [f"index={item.index}", f"kind={item.kind}"]
        for key in (
            "content_type",
            "filename",
            "local_ref",
            "provider_ref",
            "source_message_id",
        ):
            value = getattr(item, key)
            if value is not None:
                parts.append(f"{key}={self._bounded_attachment_text(value, 1024)}")
        if item.transcript is not None:
            parts.append(
                "transcript="
                + self._bounded_attachment_text(item.transcript, 1200)
            )
        if item.content_summary is not None:
            parts.append(
                "content_summary="
                + self._bounded_attachment_text(item.content_summary, 1200)
            )
        parts.append(f"staged={'true' if item.staged else 'false'}")
        return " ".join(parts)[:4096]

    def _bounded_attachment_text(self, value: str, limit: int) -> str:
        redacted = str(self._redactor.redact(value))
        normalized = " ".join(redacted.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 1)].rstrip() + "…"

    def _redacted_text(self, value: str) -> str:
        return cast(str, self._redactor.redact(value))

    def _write_audit(
        self,
        prepared: PreparedRequest,
        request: CoreRequest,
    ) -> None:
        self._audit_writer.write(
            AuditEvent(
                event_type="request.prepared",
                actor=request.actor,
                request_id=prepared.request_id,
                project_id=prepared.project_id,
                task_id=prepared.task_id,
                payload={
                    "request_id": prepared.request_id,
                    "channel": request.channel,
                    "project_id": prepared.project_id,
                    "task_id": prepared.task_id,
                    "route": prepared.route_decision.route.value,
                    "capability": (
                        prepared.capability_decision.capability.value
                    ),
                    "persona_version": prepared.persona.version,
                    "persona_content_hash": prepared.persona.content_hash,
                    "token_estimate": prepared.context.estimated_tokens,
                    "warning_count": len(prepared.warnings),
                    **(
                        {"attachment_count": len(request.attachments)}
                        if request.attachments
                        else {}
                    ),
                    **(
                        {
                            "workflow_policy_rule": (
                                prepared.workflow.policy_rule_id
                            ),
                            "workflow_risk_level": int(
                                prepared.workflow.risk_level
                            ),
                            "workflow_approval_required": (
                                prepared.workflow.approval_required
                            ),
                        }
                        if prepared.workflow is not None
                        else {}
                    ),
                },
            )
        )
