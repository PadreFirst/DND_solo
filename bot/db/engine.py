from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings

log = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    from bot.models.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_auto_migrate)


def _auto_migrate(conn) -> None:
    """Add missing columns to existing tables (SQLite-safe ALTER TABLE ADD COLUMN)."""
    from bot.models.base import Base

    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            col_type = col.type.compile(dialect=conn.dialect)
            default = ""
            if col.default is not None:
                default_val = col.default.arg
                if isinstance(default_val, str):
                    default = f" DEFAULT '{default_val}'"
                elif isinstance(default_val, (int, float)):
                    default = f" DEFAULT {default_val}"
                elif isinstance(default_val, bool):
                    default = f" DEFAULT {int(default_val)}"
            elif col.nullable:
                default = " DEFAULT NULL"
            else:
                if "INT" in str(col_type).upper():
                    default = " DEFAULT 0"
                elif "VARCHAR" in str(col_type).upper() or "TEXT" in str(col_type).upper():
                    default = " DEFAULT ''"
                else:
                    default = " DEFAULT 0"

            sql = f'ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default}'
            log.info("Auto-migrate: %s", sql)
            conn.execute(text(sql))


async def get_session() -> AsyncSession:
    async with async_session() as session:
        return session
