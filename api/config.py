from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from crawler.config import (
    DEFAULT_KEYWORD,
    DEFAULT_LANG,
    DEFAULT_TIME_WINDOW,
    DEFAULT_WORKERS,
    TIMEOUT,
)


class Settings(BaseSettings):
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    APP_ENV: str = "development"

    CRON_API_KEY: str = "test-secret-key-123"

    # Defaults compatible with crawler/cli.py
    DEFAULT_KEYWORD: str = DEFAULT_KEYWORD
    DEFAULT_MAX_ARTICLES: int = 20
    DEFAULT_WORKERS: int = DEFAULT_WORKERS
    DEFAULT_LANG: str = DEFAULT_LANG
    DEFAULT_TIME_WINDOW: str | None = DEFAULT_TIME_WINDOW
    DEFAULT_TIMEOUT: int = TIMEOUT
    DEFAULT_PROXY: str | None = None
    DEFAULT_ROTATE_UA: bool = False
    DEFAULT_RESUME: bool = True
    DEFAULT_SHOW_PROGRESS: bool = False
    DEFAULT_STORAGE_MODE: str = "google"

    STORAGE_DIR: str = "storage"
    JOBS_METADATA_DIR: str = "storage/jobs"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def storage_path(self) -> Path:
        p = Path(self.STORAGE_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def jobs_metadata_path(self) -> Path:
        p = Path(self.JOBS_METADATA_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
