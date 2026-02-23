from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

BOT_VERSION = "0.4.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    gemini_api_key: str
    database_url: str = "sqlite+aiosqlite:///./dnd_bot.db"
    debug: bool = False

    gemini_model: str = "gemini-3-flash-preview"
    gemini_model_heavy: str = ""
    gemini_model_light: str = ""
    gemini_proxy: str = ""

    webapp_port: int = 8080
    webapp_url: str = ""

    max_recent_messages: int = 12
    summarize_every_n: int = 15
    personalization_every_n: int = 10


settings = Settings()  # type: ignore[call-arg]
