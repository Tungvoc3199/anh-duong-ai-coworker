#!/usr/bin/env bash
set -euo pipefail

echo "=== SYSTEMD ==="
sudo systemctl status anh-duong-core.service --no-pager || true

echo
echo "=== PORT 8790 ==="
ss -ltnp | grep ':8790' || true

echo
echo "=== HEALTH ==="
curl -fsS http://127.0.0.1:8790/health || true
echo

echo
echo "=== READY ==="
curl -fsS http://127.0.0.1:8790/ready || true
echo

echo
echo "=== RECENT LOGS ==="
journalctl -u anh-duong-core.service -n 30 --no-pager || true
