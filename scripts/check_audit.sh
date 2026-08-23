#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/thadc/AIOS/anh-duong-core"
STATE_DIR="/home/thadc/.local/state/anh-duong-core"
AUDIT_FILE="${STATE_DIR}/audit-check.jsonl"

cd "${PROJECT_ROOT}"
source .venv/bin/activate

mkdir -p "${STATE_DIR}"
chmod 700 "${STATE_DIR}"
rm -f "${AUDIT_FILE}"

python - <<'PY'
from pathlib import Path

from app.audit import AuditEvent, AuditWriter

path = Path(
    "/home/thadc/.local/state/"
    "anh-duong-core/audit-check.jsonl"
)
writer = AuditWriter(path)

writer.write(
    AuditEvent(
        event_type="audit.check",
        actor="user",
        payload={
            "authorization": "Bearer must-not-appear",
            "safe": "visible",
        },
    )
)

result = writer.verify_integrity()
print(f"valid={result.valid}")
print(f"lines={result.line_count}")
print(path.read_text(encoding="utf-8").strip())
PY

if grep -q "must-not-appear" "${AUDIT_FILE}"; then
  echo "ERROR: Secret redaction failed."
  exit 1
fi

echo "Audit check passed."
