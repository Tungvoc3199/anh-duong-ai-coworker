#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/mnt/f/AIOS/anh-duong-core"
STATE_DIR="/home/thadc/.local/state/anh-duong-core"
CHECK_DB="${STATE_DIR}/memory-fts-check.db"
CHECK_URL="sqlite+pysqlite:////home/thadc/.local/state/anh-duong-core/memory-fts-check.db"

cd "${PROJECT_ROOT}"
source .venv/bin/activate

mkdir -p "${STATE_DIR}"
chmod 700 "${STATE_DIR}"
rm -f "${CHECK_DB}" "${CHECK_DB}-wal" "${CHECK_DB}-shm"

ANH_DUONG_DATABASE_URL="${CHECK_URL}" \
  alembic -c alembic.ini upgrade head

CHECK_URL="${CHECK_URL}" python - <<'PY'
import os

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import create_db_engine
from app.memory import MemoryRepository, MemoryType

engine = create_db_engine(os.environ["CHECK_URL"])
factory = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
    autoflush=False,
)

with factory.begin() as session:
    repository = MemoryRepository(session)
    memory = repository.create(
        memory_type=MemoryType.PROJECT,
        scope_id="proj_memory_check",
        title="Runtime architecture",
        content="Tailscale chạy trên Windows host.",
        importance=0.9,
        confidence=1.0,
        tags=("tailscale", "windows"),
    )

    results = repository.search_fts(
        "Tailscale Windows",
        scope_id="proj_memory_check",
    )

    if not results or results[0].id != memory.id:
        raise SystemExit("FTS5 search did not return the created memory")

    objects = {
        name: object_type
        for name, object_type in session.execute(
            text(
                """
                SELECT name, type
                FROM sqlite_master
                WHERE name IN (
                    'memories_fts',
                    'memories_fts_ai',
                    'memories_fts_ad',
                    'memories_fts_au'
                )
                """
            )
        )
    }

    print(f"memory_id={memory.id}")
    print(f"result_title={results[0].title}")
    print(f"fts_objects={objects}")

engine.dispose()
PY

echo "Memory FTS5 check passed."
