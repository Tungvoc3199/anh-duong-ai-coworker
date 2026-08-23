#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="/home/thadc/.local/state/anh-duong-core"
CHECK_DB="${STATE_DIR}/task-check.db"
CHECK_AUDIT="${STATE_DIR}/task-check-audit.jsonl"

cd "${PROJECT_ROOT}"
source .venv/bin/activate

mkdir -p "${STATE_DIR}"
chmod 700 "${STATE_DIR}"
rm -f "${CHECK_DB}" "${CHECK_AUDIT}"

python - <<'PY'
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.audit import AuditWriter
from app.db.base import Base
from app.db.session import create_db_engine
from app.projects import (
    ProjectCreate,
    ProjectRepository,
    ProjectService,
)
from app.tasks import (
    TaskCreate,
    TaskRepository,
    TaskService,
    TaskStatus,
)

database_url = (
    "sqlite+pysqlite:////home/thadc/.local/state/"
    "anh-duong-core/task-check.db"
)
audit_path = Path(
    "/home/thadc/.local/state/"
    "anh-duong-core/task-check-audit.jsonl"
)

engine = create_db_engine(database_url)
Base.metadata.create_all(engine)
factory = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
    autoflush=False,
)

with factory.begin() as session:
    audit_writer = AuditWriter(audit_path, fsync=False)

    project = ProjectService(
        ProjectRepository(session),
        audit_writer,
    ).create(
        ProjectCreate(
            name="Task Registry Check",
            slug="task-registry-check",
        )
    )

    service = TaskService(
        TaskRepository(session),
        audit_writer,
    )
    task = service.create(
        TaskCreate(
            project_id=project.id,
            title="Task Registry smoke test",
            description="Run the complete happy path.",
        )
    )

    for status in (
        TaskStatus.PLANNING,
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.VERIFYING,
    ):
        task = service.transition(task.id, status)

    task = service.transition(
        task.id,
        TaskStatus.COMPLETED,
        result_summary="Smoke test completed.",
    )

    print(f"id={task.id}")
    print(f"project_id={task.project_id}")
    print(f"status={task.status.value}")
    print(f"version={task.version}")
    print(f"result_summary={task.result_summary}")

engine.dispose()
PY

echo "Task Registry check passed."
