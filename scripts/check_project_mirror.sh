#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/project_env.sh"
CHECK_ROOT="$(mktemp -d /tmp/anh-duong-project-mirror.XXXXXX)"

cleanup() {
  rm -rf "${CHECK_ROOT}"
}
trap cleanup EXIT

cd "${PROJECT_ROOT}"
activate_project_venv

PROJECT_ROOT="${PROJECT_ROOT}" CHECK_ROOT="${CHECK_ROOT}" python - <<'PY'
import os
from datetime import UTC, datetime
from pathlib import Path

from app.projects import (
    Project,
    ProjectMirror,
    ProjectPriority,
    ProjectStatus,
)

now = datetime.now(UTC)
project = Project(
    id="proj_mirror_check",
    name="Ánh Dương Core Mirror Check",
    slug="anh-duong-core-mirror-check",
    status=ProjectStatus.ACTIVE,
    priority=ProjectPriority.HIGH,
    path_windows=os.environ["PROJECT_ROOT"],
    path_wsl=os.environ["PROJECT_ROOT"],
    repo_url=None,
    current_phase="Phase 3",
    owner="user",
    summary="Project Markdown Mirror smoke test.",
    next_action="Verify mirror files.",
    constraints=("local-first",),
    created_at=now,
    updated_at=now,
    last_activity_at=now,
    version=1,
)

root = Path(os.environ["CHECK_ROOT"])
project_dir = ProjectMirror(root).write_snapshot(project)

for filename in (
    "PROJECT.md",
    "STATE.md",
    "CHANGELOG.md",
    "DECISIONS.md",
):
    path = project_dir / filename
    if not path.is_file():
        raise SystemExit(f"Missing mirror file: {path}")
    print(path)

state = (project_dir / "STATE.md").read_text(encoding="utf-8")
if "**active**" not in state:
    raise SystemExit("STATE.md does not contain active status")

if list(project_dir.glob(".*.tmp")):
    raise SystemExit("Temporary files were not cleaned")

print("Project Markdown Mirror check passed.")
PY
