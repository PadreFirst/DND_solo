from __future__ import annotations

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.db import SessionLocal, init_db
from bot.handlers import router
from bot.services.game_service import GameService
from bot.services.gemini import GeminiClient
from bot.web import create_app


logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger(__name__)


async def _db_middleware(handler, event, data):
    async with SessionLocal() as session:
        data["db"] = session
        try:
            result = await handler(event, data)
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


async def run() -> None:
    await init_db()
    gemini = GeminiClient()
    game = GameService(gemini)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware.register(_db_middleware)
    dp["game"] = game
    dp.include_router(router)

    app = create_app(game)
    config = uvicorn.Config(app, host=settings.web_host, port=settings.web_port, log_level="info")
    server = uvicorn.Server(config)

    async def _run_web() -> None:
        try:
            await server.serve()
        except SystemExit as exc:
            # Uvicorn may raise SystemExit on bind errors (e.g. port already in use).
            # Keep Telegram polling alive instead of stopping the whole bot.
            log.error("Web server failed to start, continuing bot-only mode: %s", exc)

    async def _run_bot():
        await dp.start_polling(bot)

    log.info("Starting Telegram bot + API server")
    try:
        await asyncio.gather(_run_web(), _run_bot())
    finally:
        await gemini.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
