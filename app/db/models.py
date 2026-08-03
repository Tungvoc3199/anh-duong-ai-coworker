from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampVersionMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ProjectRow(TimestampVersionMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_slug", "slug", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="idea", index=True)
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    path_windows: Mapped[str | None] = mapped_column(Text)
    path_wsl: Mapped[str | None] = mapped_column(Text)
    repo_url: Mapped[str | None] = mapped_column(Text)
    current_phase: Mapped[str | None] = mapped_column(String(128))
    owner: Mapped[str] = mapped_column(String(128), default="user")
    summary: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    constraints: Mapped[list[Any]] = mapped_column(JSON, default=list)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectPhaseRow(TimestampVersionMixin, Base):
    __tablename__ = "project_phases"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_project_phase_name"),
        Index("ix_project_phases_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="not_started")
    summary: Mapped[str | None] = mapped_column(Text)


class TaskRow(TimestampVersionMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="received")
    priority: Mapped[str] = mapped_column(String(32), default="normal")
    risk_level: Mapped[int] = mapped_column(Integer, default=0)
    requested_by: Mapped[str] = mapped_column(String(128), default="user")
    source_channel: Mapped[str] = mapped_column(String(64), default="api")
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    current_step_id: Mapped[str | None] = mapped_column(String(64))
    result_summary: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowRow(TimestampVersionMixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (
        Index("ix_workflows_status", "status"),
        Index("ix_workflows_task_id", "task_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    current_step_id: Mapped[str | None] = mapped_column(String(64))
    context_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_summary: Mapped[str | None] = mapped_column(Text)


class WorkflowStepRow(TimestampVersionMixin, Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        Index("ix_workflow_steps_workflow_id", "workflow_id"),
        Index("ix_workflow_steps_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    step_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    skill_id: Mapped[str | None] = mapped_column(String(255))
    risk_level: Mapped[int] = mapped_column(Integer, default=0)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalRow(TimestampVersionMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_status", "status"),
        Index("ix_approvals_workflow_id", "workflow_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="single_action")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    preview: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(128))


class MemoryRow(TimestampVersionMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_scope_id", "scope_id"),
        Index("ix_memories_type", "memory_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class MemoryLinkRow(TimestampVersionMixin, Base):
    __tablename__ = "memory_links"
    __table_args__ = (
        UniqueConstraint(
            "source_memory_id",
            "target_memory_id",
            "relation",
            name="uq_memory_link",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    target_memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(64), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class ConsolidationJobRow(TimestampVersionMixin, Base):
    __tablename__ = "memory_consolidation_jobs"
    __table_args__ = (
        UniqueConstraint("workflow_id", name="uq_consolidation_workflow"),
        Index("ix_consolidation_jobs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class SkillRow(TimestampVersionMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (Index("ix_skills_skill_id", "skill_id", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[int] = mapped_column(Integer, default=0)
    approval_policy: Mapped[str] = mapped_column(String(32), default="conditional")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    idempotent: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    skill_version: Mapped[str] = mapped_column(String(64), default="1.0")


class SkillExecutionRow(TimestampVersionMixin, Base):
    __tablename__ = "skill_executions"
    __table_args__ = (
        Index("ix_skill_executions_created_at", "created_at"),
        Index("ix_skill_executions_workflow_id", "workflow_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_steps.id", ondelete="SET NULL")
    )
    skill_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PersonaVersionRow(TimestampVersionMixin, Base):
    __tablename__ = "persona_versions"
    __table_args__ = (Index("ix_persona_versions_version_name", "version_name", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_name: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    changelog: Mapped[str | None] = mapped_column(Text)


class PolicyVersionRow(TimestampVersionMixin, Base):
    __tablename__ = "policy_versions"
    __table_args__ = (Index("ix_policy_versions_version_name", "version_name", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_name: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    changelog: Mapped[str | None] = mapped_column(Text)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_event_type", "event_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AsyncTaskRunRow(TimestampVersionMixin, Base):
    __tablename__ = "async_task_runs"
    __table_args__ = (
        Index("ix_async_task_runs_status", "status"),
        Index("ix_async_task_runs_run_after", "run_after"),
        Index(
            "ix_async_task_runs_lease_expires_at",
            "lease_expires_at",
        ),
        Index(
            "ix_async_task_runs_notification_status",
            "notification_status",
        ),
        UniqueConstraint(
            "task_id",
            name="uq_async_task_runs_task_id",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_async_task_runs_idempotency_key",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    goal: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    workspace: Mapped[str | None] = mapped_column(
        String(1024),
    )
    request_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    checkpoint_json: Mapped[str | None] = mapped_column(
        Text,
    )
    result_json: Mapped[str | None] = mapped_column(
        Text,
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    lease_owner: Mapped[str | None] = mapped_column(
        String(128),
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    external_run_id: Mapped[str | None] = mapped_column(
        String(255),
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(128),
    )
    last_error_message: Mapped[str | None] = mapped_column(
        Text,
    )
    source_chat_id: Mapped[str | None] = mapped_column(
        String(128),
    )
    notification_status: Mapped[str] = mapped_column(
        String(32),
        default="not_required",
        nullable=False,
    )
    notification_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
