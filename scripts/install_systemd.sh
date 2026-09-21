#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="/home/thadc/.config/anh-duong-core"
STATE_DIR="/home/thadc/.local/state/anh-duong-core"
UNIT_SOURCE="${PROJECT_ROOT}/systemd/anh-duong-core.service"
UNIT_TARGET="/etc/systemd/system/anh-duong-core.service"

if [[ ! -x "${PROJECT_ROOT}/.venv/bin/uvicorn" ]]; then
  echo "ERROR: Chưa có virtualenv hoặc uvicorn."
  echo "Chạy trước: cd ${PROJECT_ROOT} && ./scripts/setup.sh"
  exit 1
fi

mkdir -p "${CONFIG_DIR}" "${STATE_DIR}"
chmod 700 "${CONFIG_DIR}" "${STATE_DIR}"

if [[ ! -f "${CONFIG_DIR}/.env" ]]; then
  cp "${PROJECT_ROOT}/.env.example" "${CONFIG_DIR}/.env"
fi
chmod 600 "${CONFIG_DIR}/.env"

sudo install -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
sudo systemctl daemon-reload
sudo systemctl enable --now anh-duong-core.service

echo
sudo systemctl status anh-duong-core.service --no-pager
echo
"${PROJECT_ROOT}/scripts/runtime_truth.sh"
