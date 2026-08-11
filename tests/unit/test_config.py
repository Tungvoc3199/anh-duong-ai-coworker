from app.config import Settings

EXPECTED_DB_URL = "sqlite+pysqlite:////home/thadc/.local/state/anh-duong-core/anh_duong.db"


def test_settings_use_absolute_linux_database_path(monkeypatch) -> None:
    monkeypatch.delenv("ANH_DUONG_DATABASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_url == EXPECTED_DB_URL
    assert "./state/" not in settings.database_url


def test_settings_default_openclaw_gateway(monkeypatch) -> None:
    monkeypatch.delenv("ANH_DUONG_OPENCLAW_BASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.openclaw_base_url == "http://127.0.0.1:18789"
