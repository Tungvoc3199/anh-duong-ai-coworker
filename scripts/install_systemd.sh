#!/usr/bin/env bash
set -euo pipefail

RELEASE_ROOT="/home/thadc/AIOS/releases/anh-duong-core"
ACTIVE_RELEASE="${RELEASE_ROOT}/current"
CONFIG_DIR="/home/thadc/.config/anh-duong-core"
STATE_DIR="/home/thadc/.local/state/anh-duong-core"
UNIT_SOURCE="${ACTIVE_RELEASE}/systemd/anh-duong-core.service"
UNIT_TARGET="/etc/systemd/system/anh-duong-core.service"

if [[ ! -L "${ACTIVE_RELEASE}" ]] || [[ ! -d "${ACTIVE_RELEASE}" ]]; then
  echo "ERROR: active release is absent: ${ACTIVE_RELEASE}"
  echo "Create and validate an immutable release, then atomically set current first."
  exit 1
fi
if [[ ! -x "${ACTIVE_RELEASE}/.venv/bin/uvicorn" ]]; then
  echo "ERROR: active release virtualenv or uvicorn is absent."
  echo "Validate ${ACTIVE_RELEASE} before installing the unit."
  exit 1
fi
if [[ ! -f "${UNIT_SOURCE}" ]]; then
  echo "ERROR: canonical unit is absent from active release: ${UNIT_SOURCE}"
  exit 1
fi

# The approved release preflight must preserve the actual system-unit scope and
# fragment before installation. This installer supports only the canonical
# system unit target and fails rather than silently replacing a user/custom unit.
CURRENT_FRAGMENT="$(sudo systemctl show -p FragmentPath --value anh-duong-core.service 2>/dev/null || true)"
if [[ -n "${CURRENT_FRAGMENT}" ]] && [[ "${CURRENT_FRAGMENT}" != "${UNIT_TARGET}" ]]; then
  echo "ERROR: existing unit fragment differs from canonical system target: ${CURRENT_FRAGMENT}"
  echo "Capture the first-migration preimage and use the detected scope before proceeding."
  exit 1
fi

mkdir -p "${CONFIG_DIR}" "${STATE_DIR}"
chmod 700 "${CONFIG_DIR}" "${STATE_DIR}"

if [[ ! -f "${CONFIG_DIR}/.env" ]]; then
  cp "${ACTIVE_RELEASE}/.env.example" "${CONFIG_DIR}/.env"
fi
chmod 600 "${CONFIG_DIR}/.env"

sudo install -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
sudo systemctl daemon-reload
sudo systemctl enable anh-duong-core.service

echo "Installed release-safe unit for ${ACTIVE_RELEASE}."
echo "No restart was performed. Restart only in an approved release transition."
sudo systemctl show -p FragmentPath -p WorkingDirectory -p ExecStart anh-duong-core.service
