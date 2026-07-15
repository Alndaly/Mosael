from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIBU_", env_file=".env", extra="ignore")

    data_dir: Path = Path.home() / ".mibu-new"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8800
    scheduler_enabled: bool = True
    feishu_autostart: bool = True

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mibu.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def plugins_dir(self) -> Path:
        return self.data_dir / "plugins"


settings = Settings()
