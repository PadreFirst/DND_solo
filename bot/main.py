"""Entry point — starts the bot in polling mode with an embedded web server for the Mini App."""
from __future__ import annotations

import asyncio
import logging
import sys

from aiohttp import web
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
from bot.web.server import create_app


def setup_logging() -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


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


_shutdown_event = asyncio.Event()


def _handle_signal() -> None:
    _shutdown_event.set()


async def _run_web_server() -> None:
    log = logging.getLogger(__name__)
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webapp_port)
    await site.start()
    log.info("Web server started on 0.0.0.0:%d", settings.webapp_port)
    try:
        await _shutdown_event.wait()
    finally:
        await runner.cleanup()


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

    import signal
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    log.info("Bot starting in polling mode + web server on port %d...", settings.webapp_port)
    await asyncio.gather(
        dp.start_polling(bot),
        _run_web_server(),
    )


if __name__ == "__main__":
    asyncio.run(main())
