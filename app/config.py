from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_STATE_DIR = Path("/home/thadc/.local/state/anh-duong-core")
DEFAULT_DATABASE_URL = "sqlite+pysqlite:////home/thadc/.local/state/anh-duong-core/anh_duong.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANH_DUONG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Ánh Dương Core"
    app_version: str = "0.1.0"
    database_url: str = DEFAULT_DATABASE_URL
    audit_path: Path = DEFAULT_STATE_DIR / "audit.jsonl"
    data_root: Path = Path("/mnt/f/AIOS/anh-duong-data")
    openclaw_base_url: str = "http://127.0.0.1:18789"
    openclaw_execution_path: str = "/v1/responses"
    openclaw_notification_path: str = "/tools/invoke"
    openclaw_timeout_seconds: float = 600.0
    openclaw_notification_timeout_seconds: float = 30.0
    openclaw_auth_token: str | None = None
    openclaw_container_name: str = "openclaw-openclaw-gateway-1"
    openclaw_image_model: str = "openai/gpt-image-2"
    openclaw_image_timeout_seconds: float = 600.0
    openclaw_image_output_root: Path = Path(
        "/home/thadc/.openclaw/media/tool-image-generation"
    )
    openclaw_image_container_output_root: str = (
        "/home/node/.openclaw/media/tool-image-generation"
    )
    visualforge_root: Path = Path("/home/thadc/AIOS/visualforge")
    visualforge_expected_commit: str = "aac8cbf6bf21f03d2338d81da8764e990055c4d2"
    visualforge_python_executable: str = "/usr/bin/python3"
    visualforge_timeout_seconds: float = 20.0
    internal_api_token: str | None = None
    async_worker_enabled: bool = True
    async_worker_poll_seconds: float = 2.0
    async_worker_lease_seconds: int = 900
    async_worker_shutdown_seconds: float = 30.0
    async_worker_workspace_roots: tuple[Path, ...] = (
        Path("/mnt/f/AIOS"),
    )
    log_level: str = "INFO"
    approval_hmac_secret: str = "change-me"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
