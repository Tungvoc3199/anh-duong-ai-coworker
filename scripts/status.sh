#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== RUNTIME TRUTH ==="
truth_rc=0
"${SCRIPT_DIR}/runtime_truth.sh" || truth_rc=$?

echo
echo "=== RECENT LOGS ==="
journalctl -u anh-duong-core.service -n 30 --no-pager || true

exit "${truth_rc}"
