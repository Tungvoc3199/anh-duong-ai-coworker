from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app.db.session import create_db_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def migrated_engine(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path}/migrated.db"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_db_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
