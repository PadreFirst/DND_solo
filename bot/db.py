from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings
from bot.models import Base


engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Best-effort "in place" migrations — create_all only creates missing
        # TABLES, not missing COLUMNS. When we add a new column to an
        # existing model the prod SQLite file would still be stuck on the
        # old schema. These ALTERs fail harmlessly if the column already
        # exists; that's exactly what we want.
        for stmt in _SOFT_MIGRATIONS:
            try:
                await conn.exec_driver_sql(stmt)
            except Exception:
                pass


_SOFT_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE game_sessions ADD COLUMN scene_state_json TEXT DEFAULT '[]'",
    "ALTER TABLE game_sessions ADD COLUMN has_light_source BOOLEAN DEFAULT 1",
    "ALTER TABLE game_sessions ADD COLUMN onboarding_state_json TEXT DEFAULT ''",
    "ALTER TABLE characters ADD COLUMN death_saves_success INTEGER DEFAULT 0",
    "ALTER TABLE characters ADD COLUMN death_saves_failure INTEGER DEFAULT 0",
    "ALTER TABLE characters ADD COLUMN resistances_json TEXT DEFAULT '{\"resist\":[],\"immune\":[],\"vulnerable\":[]}'",
    "ALTER TABLE characters ADD COLUMN hit_dice_remaining INTEGER DEFAULT 1",
    "ALTER TABLE characters ADD COLUMN hit_dice_max INTEGER DEFAULT 1",
    "ALTER TABLE characters ADD COLUMN powers_json TEXT DEFAULT '[]'",
    "ALTER TABLE characters ADD COLUMN pending_level_ups INTEGER DEFAULT 0",
    "ALTER TABLE characters ADD COLUMN pending_levelup_offer_json TEXT DEFAULT ''",
    "ALTER TABLE npc_state ADD COLUMN is_companion BOOLEAN DEFAULT 0",
    "ALTER TABLE npc_state ADD COLUMN attack_bonus INTEGER DEFAULT 3",
    "ALTER TABLE npc_state ADD COLUMN damage_dice VARCHAR(24) DEFAULT '1d6'",
    "ALTER TABLE npc_state ADD COLUMN damage_type VARCHAR(24) DEFAULT ''",
    "ALTER TABLE npc_state ADD COLUMN initiative_bonus INTEGER DEFAULT 0",
    "ALTER TABLE npc_state ADD COLUMN role VARCHAR(120) DEFAULT ''",
    "ALTER TABLE npc_state ADD COLUMN last_seen_turn INTEGER DEFAULT 0",
    "ALTER TABLE npc_state ADD COLUMN faction VARCHAR(120) DEFAULT ''",
    "ALTER TABLE game_sessions ADD COLUMN current_beat VARCHAR(160) DEFAULT ''",
    "ALTER TABLE game_sessions ADD COLUMN last_quest_create_turn INTEGER DEFAULT 0",
    "ALTER TABLE quests ADD COLUMN deadline_turns_remaining INTEGER DEFAULT 0",
    "ALTER TABLE quests ADD COLUMN last_updated_turn INTEGER DEFAULT 0",
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
