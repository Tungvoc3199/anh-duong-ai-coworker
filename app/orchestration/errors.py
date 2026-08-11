class CoreRequestPipelineError(RuntimeError):
    """Base error for request-preparation failures."""


class ProjectContextNotFound(CoreRequestPipelineError):
    """Raised when a requested Project Registry record is absent."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"Project not found: {project_id}")


class TaskContextNotFound(CoreRequestPipelineError):
    """Raised when a requested Task Registry record is absent."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"Task not found: {task_id}")


class TaskProjectMismatch(CoreRequestPipelineError):
    """Raised when explicit Task and Project context disagree."""

    def __init__(
        self,
        *,
        task_id: str,
        task_project_id: str,
        requested_project_id: str,
    ) -> None:
        self.task_id = task_id
        self.task_project_id = task_project_id
        self.requested_project_id = requested_project_id
        super().__init__(
            "Task/project context mismatch: "
            f"task {task_id} belongs to {task_project_id}, "
            f"not {requested_project_id}"
        )


class ProjectResolutionFailed(CoreRequestPipelineError):
    """Raised when a workflow has no deterministic Project Registry match."""

    def __init__(self) -> None:
        super().__init__(
            "Workflow requires exactly one active project when no project "
            "or task context is explicit."
        )


class WorkflowPreparationFailed(CoreRequestPipelineError):
    """Raised when transport metadata cannot form a safe async request."""
