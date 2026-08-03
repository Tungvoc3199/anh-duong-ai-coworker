#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="/home/thadc/.local/state/anh-duong-core"

mkdir -p "${STATE_DIR}"
chmod 700 "${STATE_DIR}"

cd "${PROJECT_ROOT}"
source .venv/bin/activate
alembic upgrade head
printf 'Database initialized: %s\n' "${STATE_DIR}/anh_duong.db"
