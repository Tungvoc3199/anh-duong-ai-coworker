#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="anh-duong-core.service"
BASE_URL="http://127.0.0.1:8790"
MAX_WAIT_SECONDS=30

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

  if curl -fsS "${BASE_URL}/ready" >/tmp/anh-duong-core-ready.json 2>/dev/null; then
    echo
    echo "Service đã sẵn sàng sau ${second} giây."

    echo "HEALTH:"
    curl -fsS "${BASE_URL}/health"
    echo

    echo "READY:"
    cat /tmp/anh-duong-core-ready.json
    echo

    rm -f /tmp/anh-duong-core-ready.json
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
