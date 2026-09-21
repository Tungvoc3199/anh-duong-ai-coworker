import asyncio

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.system_status import probe_core_status_via_asgi


def test_health_does_not_require_database(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+pysqlite:///{tmp_path}/health.db",
    )
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Ánh Dương Core",
        "version": "0.1.0",
    }


def test_ready_checks_database_connection(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+pysqlite:///{tmp_path}/ready.db",
    )
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["database"] == "ok"


def test_internal_asgi_status_probe_has_no_port_dependency(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+pysqlite:///{tmp_path}/status-probe.db",
        async_worker_enabled=False,
    )
    app = create_app(settings=settings)
    with TestClient(app):
        result = asyncio.run(probe_core_status_via_asgi(app))

    assert result["service"] == {
        "status": "running",
        "evidence": "core_asgi:/health",
    }
    assert result["health"]["http_status"] == 200
    assert result["health"]["status"] == "ok"
    assert result["ready"]["http_status"] == 200
    assert result["ready"]["status"] == "ready"
    assert result["ready"]["database"] == "ok"
