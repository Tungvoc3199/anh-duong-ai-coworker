#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/project_env.sh"
cd "${PROJECT_ROOT}"
activate_project_venv

printf 'PROJECT_ROOT=%s\n' "${PROJECT_ROOT}"
printf 'PROJECT_VENV=%s\n' "${PROJECT_VENV}"

app_file="$(
python - <<'PY'
from pathlib import Path
import app
print(Path(app.__file__).resolve())
PY
)"

case "${app_file}" in
  "${PROJECT_ROOT}"/app/*)
    printf 'APP_FILE=%s\n' "${app_file}"
    printf 'WORKTREE_IMPORT=PASS\n'
    ;;
  *)
    printf 'APP_FILE=%s\n' "${app_file}" >&2
    printf 'WORKTREE_IMPORT=FAIL\n' >&2
    exit 1
    ;;
esac
