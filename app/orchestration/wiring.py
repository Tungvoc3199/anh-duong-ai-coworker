from pathlib import Path

from sqlalchemy.orm import Session

from app.audit import AuditWriter
from app.capabilities import CapabilityRouter
from app.context_builder import create_context_builder
from app.orchestration.pipeline import CoreRequestPipeline
from app.persona import load_persona
from app.projects import ProjectRepository, ProjectService
from app.routing import FastRouter
from app.tasks import TaskRepository, TaskService


def create_core_request_pipeline(
    session: Session,
    *,
    audit_writer: AuditWriter,
    persona_root: Path,
) -> CoreRequestPipeline:
    """Compose OR-1 dependencies without preparing or executing a request."""

    return CoreRequestPipeline(
        persona_loader=lambda: load_persona(persona_root),
        fast_router=FastRouter(),
        capability_router=CapabilityRouter(),
        context_builder=create_context_builder(session),
        project_reader=ProjectService(
            ProjectRepository(session),
            audit_writer,
        ),
        task_reader=TaskService(
            TaskRepository(session),
            audit_writer,
        ),
        audit_writer=audit_writer,
    )

