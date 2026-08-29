from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.planning.models import PlanningTruthSnapshot
from app.projects.repository import ProjectRepository


class PlanningTruthError(ValueError):
    """Runtime/project truth could not be established."""


class PlanningTruthInspector:
    def __init__(
        self,
        project_repository: ProjectRepository,
        *,
        path_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self.project_repository = project_repository
        self.path_exists = path_exists or (lambda value: Path(value).exists())

    def inspect(
        self,
        project_id: str,
        workspace: str | None,
    ) -> PlanningTruthSnapshot:
        row = self.project_repository.get(project_id)
        if row is None:
            raise PlanningTruthError(f"Project not found: {project_id}")

        resolved_workspace = workspace or row.path_wsl or row.path_windows
        exists = (
            self.path_exists(resolved_workspace)
            if resolved_workspace is not None
            else False
        )
        constraints = tuple(str(value) for value in (row.constraints or []))
        return PlanningTruthSnapshot(
            project_id=row.id,
            project_version=row.version,
            project_status=row.status,
            current_phase=row.current_phase,
            workspace=resolved_workspace,
            workspace_exists=exists,
            project_constraints=constraints,
            observed_at=datetime.now(UTC),
        )
