#!/usr/bin/env bash

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CANONICAL_VENV="/home/thadc/AIOS/anh-duong-core/.venv"
PROJECT_VENV="${PROJECT_ROOT}/.venv"

if [[ ! -x "${PROJECT_VENV}/bin/python" && -x "${CANONICAL_VENV}/bin/python" ]]; then
  PROJECT_VENV="${CANONICAL_VENV}"
fi

activate_project_venv() {
  if [[ ! -x "${PROJECT_VENV}/bin/python" ]]; then
    printf 'ERROR: no usable Python venv for %s\n' "${PROJECT_ROOT}" >&2
    printf 'Run ./scripts/setup.sh or restore %s\n' "${CANONICAL_VENV}" >&2
    return 1
  fi
  # shellcheck disable=SC1091
  source "${PROJECT_VENV}/bin/activate"
}
