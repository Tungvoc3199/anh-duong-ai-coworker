from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


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
