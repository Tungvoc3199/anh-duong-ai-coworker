from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.base import Base
from app.db.session import create_db_engine
from app.main import create_app


def test_ready_async_schema_requires_gateway_bearer_token(
    tmp_path: Path,
) -> None:
    engine = create_db_engine(
        "sqlite+pysqlite:///"
        f"{tmp_path / 'security-runtime.db'}"
    )
    Base.metadata.create_all(engine)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        audit_path=tmp_path / "security-audit.jsonl",
        internal_api_token="internal-test",
        openclaw_auth_token=None,
        async_worker_enabled=True,
        async_worker_workspace_roots=(tmp_path,),
    )
    app = create_app(settings=settings, engine=engine)

    try:
        with pytest.raises(
            RuntimeError,
            match="openclaw_auth_token",
        ):
            with TestClient(app):
                pass
    finally:
        engine.dispose()
