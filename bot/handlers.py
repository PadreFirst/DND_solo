from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.services.game_service import GameService, is_gm_question
from bot.ui import menu_keyboard, options_keyboard

log = logging.getLogger(__name__)
router = Router(name="main")


@asynccontextmanager
async def typing_status(bot, chat_id):
    """Keep sending TYPING chat action every 4 s until the wrapped block finishes."""
    stop = asyncio.Event()

    async def _loop():
        while not stop.is_set():
            try:
                await bot.send_chat_action(chat_id, ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=4.0)
                return
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _render_options_block(options: list[str]) -> str:
    rows = [f"{idx}) {opt}" for idx, opt in enumerate(options, start=1)]
    return "Варианты действий:\n" + "\n".join(rows)


def _compose_turn_message(text: str, options: list[str]) -> str:
    if not options:
        return text
    return f"{text}\n\n{_render_options_block(options)}"


@router.message(CommandStart())
async def cmd_start(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    await game.ensure_character(db, user)
    gs = await game.ensure_session(db, user)

    if gs.turn_number > 0:
        options = json.loads(gs.last_options_json or "[]")
        greeting = (
            "🎲 <b>С возвращением!</b>\n\n"
            "Продолжай игру — выбери вариант или напиши своё действие.\n"
            "Для новой кампании нажми <b>Меню → Новая игра</b>."
        )
        await message.answer(greeting, parse_mode="HTML")
        if options:
            await message.answer(
                _render_options_block(options),
                reply_markup=options_keyboard(options),
            )
        return

    greeting = (
        "🎲 <b>DND GM бот готов.</b>\n\n"
        "Опиши персонажа и сеттинг одним сообщением, и я запущу новую кампанию.\n"
        "Пример: <i>«Хочу играть за хитрого плута в мрачном киберпанк-городе»</i>"
    )
    await message.answer(greeting, parse_mode="HTML")


@router.callback_query(F.data.startswith("opt:"))
async def on_option(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    options = json.loads(gs.last_options_json or "[]")
    idx = int(cb.data.split(":")[1])
    if idx >= len(options):
        await cb.answer("Вариант устарел, отправь ход текстом.", show_alert=True)
        return
    action = options[idx]
    await cb.answer()

    if action.startswith("✏"):
        await cb.message.answer("Напиши свой вариант действия текстом:")
        return

    async with typing_status(cb.message.bot, cb.message.chat.id):
        out = await game.process_turn(db, user, action)
    await cb.message.answer(
        _compose_turn_message(out.text, out.options),
        reply_markup=options_keyboard(out.options),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:open")
async def on_menu(cb: CallbackQuery) -> None:
    try:
        await cb.message.edit_reply_markup(reply_markup=menu_keyboard(settings.web_app_url or None))
    except Exception:
        log.debug("Failed to edit reply markup for menu", exc_info=True)
    await cb.answer()


@router.callback_query(F.data == "menu:back")
async def on_menu_back(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    options = json.loads(gs.last_options_json or "[]")
    try:
        await cb.message.edit_reply_markup(reply_markup=options_keyboard(options))
    except Exception:
        log.debug("Failed to edit reply markup for back", exc_info=True)
    await cb.answer()


@router.callback_query(F.data == "menu:hint")
async def on_hint(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(
        "💡 Подсказка: смотри на окружение и комбинируй подходы.\n"
        "Используй не только бой: разговор, разведка, укрытие, предметы, отдых."
    )


@router.callback_query(F.data == "menu:character")
async def on_character(cb: CallbackQuery) -> None:
    if settings.web_app_url:
        await cb.answer("Открой мини-апп кнопкой в меню.", show_alert=True)
        return
    await cb.answer(
        "WEB_APP_URL пока не задан. API уже работает: /api/character/{telegram_user_id}",
        show_alert=True,
    )


@router.callback_query(F.data == "menu:ask")
async def on_ask(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer("Задай вопрос в формате: <code>ГМ: ...</code>", parse_mode="HTML")


@router.callback_query(F.data == "menu:new")
async def on_new_game(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    gs.turn_number = 0
    gs.combat_active = False
    gs.round_number = 0
    gs.current_location = "Неизвестная локация"
    gs.current_location_description = ""
    gs.active_quest_summary = ""
    gs.last_options_json = "[]"
    await cb.answer("Новая игра начата.", show_alert=True)
    await cb.message.answer(
        "🔄 <b>Новая игра.</b>\n\nОпиши персонажа и сеттинг, чтобы начать кампанию.\n"
        "Пример: <i>«Полуэльф-рейнджер на границе диких земель»</i>",
        parse_mode="HTML",
    )


@router.message(F.text)
async def on_text(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    gs = await game.ensure_session(db, user)
    text = message.text.strip()

    if gs.turn_number == 0:
        async with typing_status(message.bot, message.chat.id):
            out = await game.initialize_story(db, user, text)
        await message.answer(
            _compose_turn_message(out.text, out.options),
            reply_markup=options_keyboard(out.options),
            parse_mode="HTML",
        )
        return

    if is_gm_question(text):
        async with typing_status(message.bot, message.chat.id):
            out = await game.process_turn(db, user, text)
        await message.answer(
            _compose_turn_message(out.text, out.options),
            reply_markup=options_keyboard(out.options),
            parse_mode="HTML",
        )
        return

    async with typing_status(message.bot, message.chat.id):
        out = await game.process_turn(db, user, text)
    await message.answer(
        _compose_turn_message(out.text, out.options),
        reply_markup=options_keyboard(out.options),
        parse_mode="HTML",
    )
