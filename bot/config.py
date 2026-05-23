from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"
SYSTEM_PROMPT_PATH = ROOT_DIR / "system_prompt.md"


_ENV_KEY_RE = re.compile(r"^[A-Z0-9_]+$")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY_RE.match(key):
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file(ENV_PATH)


@dataclass(slots=True)
class Settings:
    bot_token: str
    gemini_api_key: str
    gemini_model: str
    gemini_model_heavy: str
    gemini_proxy: str
    gemini_proxy_token: str
    database_url: str
    debug: bool
    web_host: str
    web_port: int
    web_app_url: str


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required in environment.")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required in environment.")
    return Settings(
        bot_token=token,
        gemini_api_key=api_key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        gemini_model_heavy=os.getenv("GEMINI_MODEL_HEAVY", os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")),
        gemini_proxy=os.getenv("GEMINI_PROXY", "https://generativelanguage.googleapis.com").rstrip("/"),
        gemini_proxy_token=os.getenv("GEMINI_PROXY_TOKEN", "").strip(),
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dnd_bot.db"),
        debug=_as_bool(os.getenv("DEBUG"), default=False),
        web_host=os.getenv("WEB_HOST", "0.0.0.0"),
        web_port=int(os.getenv("WEB_PORT", "8080")),
        web_app_url=os.getenv("WEB_APP_URL", "").strip(),
    )


settings = load_settings()
