from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TikSpark Pro API"
    api_prefix: str = "/api"
    sqlite_path: str = "backend/data/tikspark.db"
    secret_key_path: str = "backend/data/secret.key"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    scheduler_enabled: bool = True
    scheduler_cron: str = "0 */6 * * *"
    scheduler_scan_interval_seconds: int = 180
    manual_review_mode: bool = False
    default_schedule_window: str = "06:00-08:00"
    admin_token: str = ""
    dispatch_jitter_min_seconds: int = 15
    dispatch_jitter_max_seconds: int = 45


    model_config = SettingsConfigDict(
        env_prefix="TIKSPARK_",
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
