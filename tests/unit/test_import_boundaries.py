from __future__ import annotations

import subprocess
import sys


def test_planning_import_does_not_depend_on_async_task_import_order() -> None:
    code = (
        "import app.planning; "
        "import app.async_tasks; "
        "from app.planning import OutcomeJudge, ExecutionFailureClassifier; "
        "assert OutcomeJudge and ExecutionFailureClassifier"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
