from __future__ import annotations

from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    webapp_url: str = Field(default="", alias="WEBAPP_URL")
    database_url: str = Field(default="sqlite:///./chaos_city.db", alias="DATABASE_URL")
    run_bot_polling: bool = Field(default=True, alias="RUN_BOT_POLLING")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8080, alias="PORT")
    app_secret: str = Field(default="change_me_to_a_long_random_secret_32_chars", alias="APP_SECRET")
    admin_ids: Annotated[List[int], NoDecode] = Field(default_factory=list, alias="ADMIN_IDS")
    enable_auto_events: bool = Field(default=True, alias="ENABLE_AUTO_EVENTS")
    auto_event_interval_minutes: int = Field(default=30, alias="AUTO_EVENT_INTERVAL_MINUTES")
    auto_event_min_population: int = Field(default=1, alias="AUTO_EVENT_MIN_POPULATION")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
