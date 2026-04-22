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
    "ALTER TABLE characters ADD COLUMN death_saves_success INTEGER DEFAULT 0",
    "ALTER TABLE characters ADD COLUMN death_saves_failure INTEGER DEFAULT 0",
    "ALTER TABLE characters ADD COLUMN resistances_json TEXT DEFAULT '{\"resist\":[],\"immune\":[],\"vulnerable\":[]}'",
    "ALTER TABLE characters ADD COLUMN hit_dice_remaining INTEGER DEFAULT 1",
    "ALTER TABLE characters ADD COLUMN hit_dice_max INTEGER DEFAULT 1",
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
