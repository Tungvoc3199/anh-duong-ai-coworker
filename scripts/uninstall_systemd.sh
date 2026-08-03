#!/usr/bin/env bash
set -euo pipefail

sudo systemctl disable --now anh-duong-core.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/anh-duong-core.service
sudo systemctl daemon-reload
sudo systemctl reset-failed

echo "Đã gỡ service anh-duong-core."
echo "Không xóa source, database hoặc file .env."
