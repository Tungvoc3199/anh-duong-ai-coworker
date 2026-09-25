#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="anh-duong-core.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAX_WAIT_SECONDS=30

effective_port() {
  systemctl show "${SERVICE_NAME}" --property=ExecStart --value 2>/dev/null |
    sed -nE 's/.*--port[= ]+([0-9]+).*/\1/p' |
    head -n 1
}

echo "Restarting ${SERVICE_NAME}..."
sudo systemctl restart "${SERVICE_NAME}"

for ((second = 1; second <= MAX_WAIT_SECONDS; second++)); do
  if ! sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo
    echo "ERROR: Service đã dừng hoặc khởi động thất bại."
    sudo systemctl status "${SERVICE_NAME}" --no-pager -l || true
    journalctl -u "${SERVICE_NAME}" -n 50 --no-pager || true
    exit 1
  fi
  port="$(effective_port)"
  if [[ -n "${port}" ]] && curl -fsS "http://127.0.0.1:${port}/ready" >/dev/null 2>&1; then
    echo
    echo "Service đã sẵn sàng sau ${second} giây trên port ${port}."
    "${SCRIPT_DIR}/runtime_truth.sh"
    exit 0
  fi

  printf '.'
  sleep 1
done

echo
echo "ERROR: Service chưa sẵn sàng sau ${MAX_WAIT_SECONDS} giây."
sudo systemctl status "${SERVICE_NAME}" --no-pager -l || true
journalctl -u "${SERVICE_NAME}" -n 50 --no-pager || true
exit 1
