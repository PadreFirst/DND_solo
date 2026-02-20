"""Entry point — starts the bot in polling mode (dev) or webhook mode (prod)."""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonCommands

from bot.config import settings
from bot.db.engine import init_db
from bot.handlers.game import router as game_router
from bot.handlers.inventory import router as inventory_router
from bot.handlers.start import router as start_router
from bot.middlewares.db_session import DbSessionMiddleware


def setup_logging() -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.debug else logging.WARNING
    )


async def set_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="New adventure / Новое приключение"),
        BotCommand(command="stats", description="Character sheet / Карточка персонажа"),
        BotCommand(command="inventory", description="Inventory / Инвентарь"),
        BotCommand(command="quest", description="Current quest / Текущее задание"),
        BotCommand(command="help", description="Help / Справка"),
    ]
    await bot.set_my_commands(commands)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def main() -> None:
    setup_logging()
    log = logging.getLogger(__name__)

    log.info("Initializing database...")
    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    await set_bot_commands(bot)

    dp = Dispatcher()

    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())

    dp.include_router(start_router)
    dp.include_router(inventory_router)
    dp.include_router(game_router)

    log.info("Bot starting in polling mode...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
