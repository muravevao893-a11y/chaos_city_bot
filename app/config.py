from __future__ import annotations

from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def normalize_database_url(value: str) -> str:
    """Return a SQLAlchemy URL that works with the bundled DB drivers.

    Many hostings give URLs like postgres://... or postgresql://...
    SQLAlchemy usually tries psycopg2 for plain postgresql://, while this project
    ships psycopg v3. So we transparently switch to postgresql+psycopg://.
    """
    url = (value or "").strip()
    if not url:
        return "sqlite:///./chatograd.db"
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


class Settings(BaseSettings):
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    webapp_url: str = Field(default="", alias="WEBAPP_URL")
    database_url: str = Field(default="postgresql+psycopg://chatograd:chatograd_password@localhost:5432/chatograd", alias="DATABASE_URL")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_recycle_seconds: int = Field(default=1800, alias="DB_POOL_RECYCLE_SECONDS")
    run_bot_polling: bool = Field(default=True, alias="RUN_BOT_POLLING")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8080, alias="PORT")
    app_secret: str = Field(default="change_me_to_a_long_random_secret_32_chars", alias="APP_SECRET")
    ai_enabled: bool = Field(default=False, alias="AI_ENABLED")
    ai_provider: str = Field(default="openrouter", alias="AI_PROVIDER")
    ai_model: str = Field(default="", alias="AI_MODEL")
    ai_daily_limit_per_chat: int = Field(default=3, alias="AI_DAILY_LIMIT_PER_CHAT")
    admin_ids: Annotated[List[int], NoDecode] = Field(default_factory=list, alias="ADMIN_IDS")
    enable_auto_events: bool = Field(default=True, alias="ENABLE_AUTO_EVENTS")
    auto_event_interval_minutes: int = Field(default=30, alias="AUTO_EVENT_INTERVAL_MINUTES")
    auto_event_min_population: int = Field(default=1, alias="AUTO_EVENT_MIN_POPULATION")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_url", mode="before")
    @classmethod
    def parse_database_url(cls, value):
        return normalize_database_url(str(value or ""))

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return value
        return [int(part.strip()) for part in str(value).split(",") if part.strip()]

    @property
    def has_bot_token(self) -> bool:
        return bool(self.bot_token and "replace_me" not in self.bot_token)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql://", "postgresql+"))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
