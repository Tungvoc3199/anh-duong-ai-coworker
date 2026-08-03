#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="/home/thadc/.local/state/anh-duong-core"
CONFIG_DIR="/home/thadc/.config/anh-duong-core"
DATA_DIR="/mnt/f/AIOS/anh-duong-data"

mkdir -p "${STATE_DIR}" "${CONFIG_DIR}" "${DATA_DIR}"/{persona,policy,projects,memory}
chmod 700 "${STATE_DIR}" "${CONFIG_DIR}"

cd "${PROJECT_ROOT}"
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

if [[ ! -f "${CONFIG_DIR}/.env" ]]; then
  cp .env.example "${CONFIG_DIR}/.env"
  chmod 600 "${CONFIG_DIR}/.env"
fi

printf 'Setup complete: %s\n' "${PROJECT_ROOT}"
