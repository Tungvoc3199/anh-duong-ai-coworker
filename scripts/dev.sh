#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/thadc/AIOS/anh-duong-core"
cd "${PROJECT_ROOT}"
source .venv/bin/activate

WATCHFILES_FORCE_POLLING=true uvicorn app.main:app   --host 127.0.0.1   --port 8791   --reload   --reload-dir app
