#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/mnt/f/AIOS/anh-duong-core"
cd "${PROJECT_ROOT}"
source .venv/bin/activate

python - <<'PY'
from pathlib import Path

from app.policy import PolicyAction, PolicyEngine

engine = PolicyEngine.with_default_roots()

samples = (
    PolicyAction(name="view_status"),
    PolicyAction(
        name="create_file",
        target_path=Path(
            "/mnt/f/AIOS/anh-duong-core/tmp/check.txt"
        ),
    ),
    PolicyAction(name="restart_service"),
    PolicyAction(name="deploy"),
    PolicyAction(name="disable_audit"),
)

for action in samples:
    decision = engine.evaluate(action)
    print(
        f"{action.name}: "
        f"decision={decision.kind.value} "
        f"risk={int(decision.effective_risk_level)} "
        f"rule={decision.rule_id}"
    )
PY
