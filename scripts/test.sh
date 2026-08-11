#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

if [[ -d .venv ]]; then
  source .venv/bin/activate
fi

python -m pytest -q
python -m compileall -q app tests

if command -v ruff >/dev/null 2>&1; then
  ruff check .
else
  printf 'NOTICE: ruff is not installed; skipped.\n'
fi

if command -v mypy >/dev/null 2>&1; then
  mypy app
else
  printf 'NOTICE: mypy is not installed; skipped.\n'
fi
