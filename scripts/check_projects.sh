#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/thadc/AIOS/anh-duong-core"
STATE_DIR="/home/thadc/.local/state/anh-duong-core"
CHECK_DB="${STATE_DIR}/project-check.db"
CHECK_AUDIT="${STATE_DIR}/project-check-audit.jsonl"

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
    ProjectStatus,
)

url = (
    "sqlite+pysqlite:////home/thadc/.local/state/"
    "anh-duong-core/project-check.db"
)
engine = create_db_engine(url)
Base.metadata.create_all(engine)
factory = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
)

with factory.begin() as session:
    service = ProjectService(
        ProjectRepository(session),
        AuditWriter(
            Path(
                "/home/thadc/.local/state/"
                "anh-duong-core/project-check-audit.jsonl"
            ),
            fsync=False,
        ),
    )
    project = service.create(
        ProjectCreate(
            name="Ánh Dương Core Check",
            slug="anh-duong-core-check",
        )
    )
    project = service.transition(
        project.id,
        ProjectStatus.PLANNED,
    )
    project = service.transition(
        project.id,
        ProjectStatus.ACTIVE,
    )

    print(f"id={project.id}")
    print(f"slug={project.slug}")
    print(f"status={project.status.value}")
    print(f"version={project.version}")

engine.dispose()
PY

echo "Project Registry check passed."
