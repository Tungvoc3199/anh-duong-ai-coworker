#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/mnt/f/AIOS/anh-duong-core"
cd "${PROJECT_ROOT}"
source .venv/bin/activate

python - <<'PY'
from pathlib import Path
from app.persona import load_persona

snapshot = load_persona(Path("data/persona"))
print(f"version={snapshot.version}")
print(f"hash={snapshot.content_hash}")
print(f"files={','.join(snapshot.file_order)}")
PY
