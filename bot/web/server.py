"""Aiohttp web server for the Telegram Mini App character dashboard."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, unquote

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.db.engine import async_session
from bot.models.character import Character
from bot.models.game_session import GameSession
from bot.models.user import User

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

XP_THRESHOLDS: dict[int, int] = {
    1: 0, 2: 300, 3: 900, 4: 2700, 5: 6500,
    6: 14000, 7: 23000, 8: 34000, 9: 48000, 10: 64000,
    11: 85000, 12: 100000, 13: 120000, 14: 140000, 15: 165000,
    16: 195000, 17: 225000, 18: 265000, 19: 305000, 20: 355000,
}


def _validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram WebApp initData using HMAC-SHA256.

    Returns parsed user data dict on success, None on failure.
    """
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        received_hash = parsed.get("hash", [""])[0]
        if not received_hash:
            return None

        data_pairs = []
        for key, values in parsed.items():
            if key == "hash":
                continue
            data_pairs.append(f"{key}={values[0]}")
        data_pairs.sort()
        data_check_string = "\n".join(data_pairs)

        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        user_json = parsed.get("user", [""])[0]
        if user_json:
            return json.loads(unquote(user_json))
        return None
    except Exception:
        log.exception("initData validation failed")
        return None


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def handle_character(request: web.Request) -> web.Response:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        init_data = request.query.get("initData", "")

    tg_user = _validate_init_data(init_data, settings.bot_token)
    if not tg_user:
        return web.json_response({"error": "unauthorized"}, status=401)

    telegram_id = tg_user.get("id")
    if not telegram_id:
        return web.json_response({"error": "no user id"}, status=400)

    async with async_session() as db:
        result = await db.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.character), selectinload(User.game_session))
        )
        user = result.scalar_one_or_none()

        if not user or not user.character:
            return web.json_response({"error": "no_character"}, status=404)

        char: Character = user.character
        gs: GameSession | None = user.game_session

        next_level = char.level + 1
        xp_next = XP_THRESHOLDS.get(next_level, 0)
        xp_current_level = XP_THRESHOLDS.get(char.level, 0)

        data = {
            "name": char.name,
            "race": char.race,
            "class": char.char_class,
            "level": char.level,
            "xp": char.xp,
            "xp_next": xp_next,
            "xp_current_level": xp_current_level,
            "hp": char.current_hp,
            "max_hp": char.max_hp,
            "ac": char.armor_class,
            "speed": char.speed,
            "proficiency_bonus": char.proficiency_bonus,
            "stats": {
                "str": char.strength,
                "dex": char.dexterity,
                "con": char.constitution,
                "int": char.intelligence,
                "wis": char.wisdom,
                "cha": char.charisma,
            },
            "modifiers": {
                "str": char.str_mod,
                "dex": char.dex_mod,
                "con": char.con_mod,
                "int": char.int_mod,
                "wis": char.wis_mod,
                "cha": char.cha_mod,
            },
            "proficient_skills": char.proficient_skills,
            "saving_throws": char.saving_throw_proficiencies,
            "abilities": char.abilities,
            "inventory": char.inventory,
            "conditions": char.conditions,
            "gold": char.gold,
            "currency": gs.currency_name if gs else "gold",
            "hit_dice": f"{char.hit_dice_current}/{char.hit_dice_max}{char.hit_dice_face}",
            "backstory": char.backstory,
            "quest": gs.current_quest if gs else "",
            "location": gs.current_location if gs else "",
            "location_desc": gs.location_description if gs else "",
            "turn": gs.turn_number if gs else 0,
            "in_combat": gs.in_combat if gs else False,
            "lang": user.language,
        }

    return web.json_response(data)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/api/character", handle_character)
    app.router.add_static("/static", STATIC_DIR, show_index=False)
    return app
