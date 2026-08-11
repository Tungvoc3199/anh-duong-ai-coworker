from pathlib import Path
from types import TracebackType
from typing import Any

import anyio.to_thread
import httpx
import pytest
from alembic.config import Config

from alembic import command
from app.db.session import create_db_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]


async def _inline_run_sync(
    func,
    *args,
    abandon_on_cancel: bool = False,
    cancellable: bool | None = None,
    limiter: object | None = None,
):
    return func(*args)


anyio.to_thread.run_sync = _inline_run_sync


class InlineClient:
    __test__ = False

    def __init__(self, app, base_url: str = "http://testserver", **_: Any) -> None:
        self.app = app
        self.base_url = base_url
        self._lifespan = None
        self._loop = None

    def __enter__(self) -> "InlineClient":
        import asyncio

        self._loop = asyncio.new_event_loop()
        self._lifespan = self.app.router.lifespan_context(self.app)
        self._run(self._lifespan.__aenter__())
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._lifespan is not None:
            self._run(self._lifespan.__aexit__(exc_type, exc, traceback))
            self._lifespan = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=self.base_url,
            ) as client:
                return await client.request(method, url, **kwargs)

        return self._run(send())

    def _run(self, awaitable):
        if self._loop is None:
            raise RuntimeError("Test client is not active")
        return self._loop.run_until_complete(awaitable)


def pytest_configure(config: pytest.Config) -> None:
    import fastapi.testclient

    fastapi.testclient.TestClient = InlineClient


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
