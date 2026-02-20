from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

BOT_VERSION = "0.4.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    gemini_api_key: str
    database_url: str = "sqlite+aiosqlite:///./dnd_bot.db"
    debug: bool = False

    gemini_model: str = "gemini-2.0-flash"
    gemini_model_heavy: str = ""
    gemini_proxy: str = ""

    max_recent_messages: int = 20
    summarize_every_n: int = 25
    personalization_every_n: int = 10


settings = Settings()  # type: ignore[call-arg]
