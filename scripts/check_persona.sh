#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/project_env.sh"
cd "${PROJECT_ROOT}"
activate_project_venv

python - <<'PY'
from pathlib import Path
from app.persona import load_persona

snapshot = load_persona(Path("data/persona"))
print(f"version={snapshot.version}")
print(f"hash={snapshot.content_hash}")
print(f"files={','.join(snapshot.file_order)}")
PY
