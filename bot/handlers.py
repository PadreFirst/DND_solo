from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
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
    # Surface the free-text escape hatch — easy to miss when the buttons feel
    # like the only path forward (UX brief #2.4).
    hint = "\n\n<i>…или просто опиши своё действие словами.</i>"
    return "Варианты действий:\n" + "\n".join(rows) + hint


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
    raw = json.loads(gs.last_options_json or "[]")
    options = raw if isinstance(raw, list) else []
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


@router.callback_query(F.data == "menu:stats")
async def on_menu_stats(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    ch = await game.ensure_character(db, user)
    await cb.message.answer(game.format_stats(ch), parse_mode="HTML")


@router.callback_query(F.data == "menu:inventory")
async def on_menu_inventory(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    ch = await game.ensure_character(db, user)
    await cb.message.answer(game.format_inventory_detailed(ch), parse_mode="HTML")


@router.callback_query(F.data == "menu:quest")
async def on_menu_quest(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    await cb.message.answer(await game.format_active_quest(db, user.id, gs), parse_mode="HTML")


# ── Slash commands (side-panel) — MUST mirror the inline menu above ──

@router.message(Command("stats"))
async def cmd_stats(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    ch = await game.ensure_character(db, user)
    await message.answer(game.format_stats(ch), parse_mode="HTML")


@router.message(Command("inventory"))
async def cmd_inventory(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    ch = await game.ensure_character(db, user)
    await message.answer(game.format_inventory_detailed(ch), parse_mode="HTML")


@router.message(Command("quest"))
async def cmd_quest(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    gs = await game.ensure_session(db, user)
    await message.answer(await game.format_active_quest(db, user.id, gs), parse_mode="HTML")


@router.message(Command("hint"))
async def cmd_hint(message: Message) -> None:
    await message.answer(
        "💡 Подсказка: смотри на окружение и комбинируй подходы.\n"
        "Используй не только бой: разговор, разведка, укрытие, предметы, отдых."
    )


@router.message(Command("new"))
async def cmd_new(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    gs = await game.ensure_session(db, user)
    gs.turn_number = 0
    gs.combat_active = False
    gs.round_number = 0
    gs.current_location = "Неизвестная локация"
    gs.current_location_description = ""
    gs.active_quest_summary = ""
    gs.last_options_json = "[]"
    gs.scene_state_json = "[]"
    await message.answer(
        "🔄 <b>Новая игра.</b>\n\nОпиши персонажа и сеттинг одним сообщением.\n"
        "Пример: <i>«Нетраннер-соло в Найт-Сити, ищет сестру»</i>",
        parse_mode="HTML",
    )


@router.message(Command("rest"))
async def cmd_rest(message: Message) -> None:
    await message.answer(
        "🌙 <b>Отдых</b>\n\n"
        "Короткий (~1 час): тратишь 1 кость хитов, восстанавливаешь HP.\n"
        "Длинный (~8 часов): полное восстановление HP, ячейки, снимаются состояния.\n\n"
        "Выбери тип:",
        reply_markup=_rest_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:rest")
async def on_menu_rest(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(
        "🌙 <b>Отдых</b>\n\nВыбери тип:",
        reply_markup=_rest_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("rest:"))
async def on_rest(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    kind = cb.data.split(":", 1)[1]
    if kind not in {"short", "long"}:
        await cb.answer("Неизвестный тип отдыха.", show_alert=True)
        return
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    out = await game.perform_rest(db, user, kind)
    await cb.answer()
    await cb.message.answer(
        _compose_turn_message(out.text, out.options),
        reply_markup=options_keyboard(out.options),
        parse_mode="HTML",
    )


def _rest_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕒 Короткий отдых", callback_data="rest:short")],
        [InlineKeyboardButton(text="🌙 Длинный отдых", callback_data="rest:long")],
    ])


@router.message(Command("combat"))
async def cmd_combat(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    gs = await game.ensure_session(db, user)
    if not gs.combat_active:
        await message.answer("⚔ Боя сейчас нет.")
        return
    scene = json.loads(gs.scene_state_json or "[]")
    header = __import__("bot.services.engine", fromlist=["format_combat_status"]).format_combat_status(gs)
    enemies = " | ".join(
        f"{e.get('name', '?')} (HP {e.get('hp_current', '?')}/{e.get('hp_max', '?')}, КД {e.get('ac', '?')})"
        for e in scene
    ) or "никого"
    await message.answer(f"{header}\n⚔ Враги: {enemies}", parse_mode="HTML")


@router.callback_query(F.data == "menu:combat")
async def on_menu_combat(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    if not gs.combat_active:
        await cb.message.answer("⚔ Боя сейчас нет.")
        return
    scene = json.loads(gs.scene_state_json or "[]")
    from bot.services.engine import format_combat_status
    enemies = " | ".join(
        f"{e.get('name', '?')} (HP {e.get('hp_current', '?')}/{e.get('hp_max', '?')}, КД {e.get('ac', '?')})"
        for e in scene
    ) or "никого"
    await cb.message.answer(f"{format_combat_status(gs)}\n⚔ Враги: {enemies}", parse_mode="HTML")


# ── Trading ──────────────────────────────────────────────────────────

@router.message(Command("shop"))
async def cmd_shop(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    npc = await game.find_active_merchant(db, user)
    await message.answer(game.format_shop(npc), parse_mode="HTML")


@router.callback_query(F.data == "menu:shop")
async def on_menu_shop(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    npc = await game.find_active_merchant(db, user)
    await cb.message.answer(game.format_shop(npc), parse_mode="HTML")


@router.message(Command("buy"))
async def cmd_buy(message: Message, game: GameService, db: AsyncSession) -> None:
    args = (message.text or "").partition(" ")[2].strip()
    if not args:
        await message.answer("Использование: <code>/buy &lt;название&gt; [количество]</code>", parse_mode="HTML")
        return
    parts = args.rsplit(" ", 1)
    qty = 1
    name = args
    if len(parts) == 2 and parts[1].isdigit():
        name = parts[0].strip()
        qty = max(1, int(parts[1]))
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    text = await game.perform_buy(db, user, name, qty)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("sell"))
async def cmd_sell(message: Message, game: GameService, db: AsyncSession) -> None:
    args = (message.text or "").partition(" ")[2].strip()
    if not args:
        await message.answer("Использование: <code>/sell &lt;название&gt; [количество]</code>", parse_mode="HTML")
        return
    parts = args.rsplit(" ", 1)
    qty = 1
    name = args
    if len(parts) == 2 and parts[1].isdigit():
        name = parts[0].strip()
        qty = max(1, int(parts[1]))
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    text = await game.perform_sell(db, user, name, qty)
    await message.answer(text, parse_mode="HTML")


# ── Crafting ──────────────────────────────────────────────────────────

@router.message(Command("craft"))
async def cmd_craft(message: Message, game: GameService, db: AsyncSession) -> None:
    args = (message.text or "").partition(" ")[2].strip()
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    ch = await game.ensure_character(db, user)
    if not args:
        await message.answer(game.format_recipes(ch), parse_mode="HTML")
        return
    text = await game.craft_item(db, user, args)
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "menu:craft")
async def on_menu_craft(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    ch = await game.ensure_character(db, user)
    await cb.message.answer(game.format_recipes(ch), parse_mode="HTML")


@router.message(Command("abilities"))
async def cmd_abilities(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    ch = await game.ensure_character(db, user)
    await message.answer(game.format_abilities(ch), parse_mode="HTML")


@router.callback_query(F.data == "menu:abilities")
async def on_menu_abilities(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    ch = await game.ensure_character(db, user)
    await cb.message.answer(game.format_abilities(ch), parse_mode="HTML")


@router.message(Command("use"))
async def cmd_use(message: Message, game: GameService, db: AsyncSession) -> None:
    args = (message.text or "").partition(" ")[2].strip()
    if not args:
        await message.answer(
            "Использование: <code>/use &lt;название&gt;</code>\n"
            "Список — /abilities",
            parse_mode="HTML",
        )
        return
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    await message.answer(
        await game.use_ability(db, user, args),
        parse_mode="HTML",
    )


@router.message(Command("quests"))
async def cmd_quests(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    await message.answer(await game.format_quest_journal(db, user), parse_mode="HTML")


@router.callback_query(F.data == "menu:quests")
async def on_menu_quests(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    await cb.message.answer(await game.format_quest_journal(db, user), parse_mode="HTML")


@router.message(Command("companions"))
async def cmd_companions(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    await message.answer(await game.format_companions(db, user), parse_mode="HTML")


@router.callback_query(F.data == "menu:companions")
async def on_menu_companions(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    await cb.message.answer(await game.format_companions(db, user), parse_mode="HTML")


# ── Level-up perk picker ─────────────────────────────────────────────
#
# Kept out of aiogram FSM (parity with /onboarding) — the offer waiting
# for the player's pick is stashed in Character.pending_levelup_offer_json
# so we don't re-spin Gemini on the callback and don't collide with
# last_options_json (which holds number-option buttons).

def _levelup_kb(offer):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for perk in offer.perks or []:
        rows.append([InlineKeyboardButton(
            text=(perk.label or perk.id)[:60],
            callback_data=f"lvl:{perk.id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_offer(offer) -> str:
    lines = [f"🎉 <b>Уровень {offer.new_level}!</b>"]
    if offer.flavor:
        lines.append(f"<i>{offer.flavor}</i>")
    lines.append("")
    lines.append("Выбери, что прокачать:")
    for perk in offer.perks or []:
        lines.append(f"\n<b>{perk.label}</b>")
        if perk.description:
            lines.append(f"  {perk.description}")
    return "\n".join(lines)


async def _run_levelup_flow(
    message_or_cb, game: GameService, db: AsyncSession, chat_id_source,
) -> None:
    user = await game.get_or_create_user(
        db, chat_id_source.from_user.id, chat_id_source.from_user.username,
    )
    ch = await game.ensure_character(db, user)
    gs = await game.ensure_session(db, user)
    target = message_or_cb
    if int(ch.pending_level_ups or 0) <= 0:
        await target.answer(
            "Нет ожидающих повышений. Уровни открываются через XP "
            "(см. /stats).",
        )
        return
    offer = await game.propose_level_up_perks(db, user, ch, gs)
    ch.pending_levelup_offer_json = json.dumps(
        {"perks": [p.model_dump() for p in offer.perks],
         "new_level": offer.new_level,
         "flavor": offer.flavor},
        ensure_ascii=False,
    )
    await target.answer(
        _format_offer(offer),
        reply_markup=_levelup_kb(offer),
        parse_mode="HTML",
    )


@router.message(Command("levelup"))
async def cmd_levelup(message: Message, game: GameService, db: AsyncSession) -> None:
    await _run_levelup_flow(message, game, db, message)


@router.callback_query(F.data == "menu:levelup")
async def on_menu_levelup(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    await _run_levelup_flow(cb.message, game, db, cb)


@router.callback_query(F.data.startswith("lvl:"))
async def on_levelup_pick(
    cb: CallbackQuery, game: GameService, db: AsyncSession,
) -> None:
    from bot.schemas import LevelUpPerk
    perk_id = cb.data.split(":", 1)[1]
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    ch = await game.ensure_character(db, user)
    try:
        stash = json.loads(ch.pending_levelup_offer_json or "{}")
    except Exception:
        stash = {}
    perks = stash.get("perks") or []
    picked = next((p for p in perks if p.get("id") == perk_id), None)
    if not picked:
        await cb.answer("Предложение устарело — открой /levelup снова.", show_alert=True)
        return
    perk = LevelUpPerk(**picked)
    summary = await game.apply_level_up_perk(db, user, perk)
    ch.pending_levelup_offer_json = ""
    await cb.answer("Применено.")
    try:
        await cb.message.edit_text(
            f"✅ <b>Выбран перк:</b> {perk.label}\n\n{summary}",
            parse_mode="HTML",
        )
    except Exception:
        await cb.message.answer(f"✅ {summary}", parse_mode="HTML")


@router.message(Command("carry"))
async def cmd_carry(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    ch = await game.ensure_character(db, user)
    await message.answer(game.format_carry(ch), parse_mode="HTML")


@router.callback_query(F.data == "menu:carry")
async def on_menu_carry(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    ch = await game.ensure_character(db, user)
    await cb.message.answer(game.format_carry(ch), parse_mode="HTML")


@router.message(Command("attunement"))
async def cmd_attunement(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    ch = await game.ensure_character(db, user)
    await message.answer(game.format_attunement(ch), parse_mode="HTML")


@router.callback_query(F.data == "menu:attunement")
async def on_menu_attunement(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    ch = await game.ensure_character(db, user)
    await cb.message.answer(game.format_attunement(ch), parse_mode="HTML")


@router.message(Command("attune"))
async def cmd_attune(message: Message, game: GameService, db: AsyncSession) -> None:
    args = (message.text or "").partition(" ")[2].strip()
    if not args:
        await message.answer("Использование: <code>/attune &lt;предмет&gt;</code>", parse_mode="HTML")
        return
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    await message.answer(await game.attune_item(db, user, args), parse_mode="HTML")


@router.message(Command("unattune"))
async def cmd_unattune(message: Message, game: GameService, db: AsyncSession) -> None:
    args = (message.text or "").partition(" ")[2].strip()
    if not args:
        await message.answer("Использование: <code>/unattune &lt;предмет&gt;</code>", parse_mode="HTML")
        return
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    await message.answer(await game.unattune_item(db, user, args), parse_mode="HTML")


# ── Guided onboarding wizard ─────────────────────────────────────────
#
# Six-step wizard: universe → tone → rating → pace → difficulty → concept text.
# State lives in gs.onboarding_state_json as a dict and is kept around AFTER
# initialize_story so build_context can replay the player's tone/rating/pace
# preferences into every system prompt. Without this the LLM forgets the
# vibe by turn 3 and drifts toward generic epic-fantasy prose.

_TOTAL_STEPS = 7

_UNIVERSES = [
    ("fantasy", "🏰 Классическое фэнтези"),
    ("dark_fantasy", "🩸 Тёмное фэнтези"),
    ("cyberpunk", "🌆 Киберпанк"),
    ("postapoc", "☢ Постапокалипсис"),
    ("space", "🚀 Космоопера"),
    ("starwars", "🛸 Звёздные войны"),
    ("horror", "👻 Хоррор"),
    ("noir", "🕵 Нуар-детектив"),
    ("lotr", "💍 Властелин Колец"),
    ("hp", "🪄 Гарри Поттер"),
]
_TONES = [
    ("epic", "🦸 Эпическая"),
    ("serious", "🗡 Серьёзная"),
    ("dark", "🌑 Тёмная и жёсткая"),
    ("humor", "🍻 Лёгкая с юмором"),
    ("noir", "🎲 Гритти-нуар"),
]
_RATINGS = [
    ("13", "13+ — приключения и битвы"),
    ("16", "16+ — кровь, мрачные темы"),
    ("18", "18+ — без цензуры"),
]
_PACES = [
    ("fast", "🚀 Быстрый"),
    ("medium", "⚖ Средний"),
    ("slow", "📜 Медленный"),
]
_DIFFICULTIES = [
    ("light", "🌱 Лайт"),
    ("normal", "⚖ Норма"),
    ("hardcore", "💀 Хардкор"),
]
# Personal stake — the dramatic anchor. Single line that lives in every
# system prompt forever and gives the LLM a wound to twist. Generic
# enough to mix with any setting; custom answer always available.
_STAKES = [
    ("loved_one", "💔 Близкий человек, которого надо спасти"),
    ("revenge",   "⚔ Месть за то, что отняли"),
    ("debt",      "💀 Долг, который пришли взыскать"),
    ("secret",    "🤐 Секрет, который нельзя раскрыть"),
    ("home",      "🏚 Дом / клан / организация под угрозой"),
    ("redemption","🩹 Грех, который надо искупить"),
]


def _label_for(table, key):
    return next((lbl for k, lbl in table if k == key), key or "—")


def _onboarding_kb(step_code: str, table, cols: int = 1):
    """Build a keyboard for a given wizard step. callback_data:
    `onb:<step_code>:<value_key>`. Always appends Back + Skip(default) buttons.
    The first step also gets a Quick-Start escape hatch so impatient
    players can blast through with defaults.
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    if step_code == "uni":
        rows.append([InlineKeyboardButton(
            text="🚀 Быстрый старт (фэнтези, эпик, 16+, средний, норма)",
            callback_data="onb:quick",
        )])
    for i in range(0, len(table), cols):
        chunk = table[i:i + cols]
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"onb:{step_code}:{key}")
            for key, label in chunk
        ])
    rows.append([
        InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"onb:{step_code}:_skip"),
        InlineKeyboardButton(text="⬅ Назад", callback_data="onb:back"),
    ])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="onb:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_STEP_ORDER = ["uni", "ton", "rat", "pac", "dif", "stk", "concept"]
_STEP_TITLES = {
    "uni":     ("🌍 В каком мире играем?",           _UNIVERSES,    2),
    "ton":     ("🎭 Какая атмосфера?",                _TONES,        1),
    "rat":     ("🔞 Уровень контента?",               _RATINGS,      1),
    "pac":     ("⏱ Темп игры?",                       _PACES,        3),
    "dif":     ("🎯 Сложность?",                      _DIFFICULTIES, 3),
    "stk":     ("💔 Что или кого ты боишься потерять?\n"
                "<i>Это станет личной ставкой — ГМ будет крутить сюжет вокруг неё.</i>",
                _STAKES,       1),
}
_STEP_FIELDS = {
    "uni": ("universe", "universe_key"),
    "ton": ("tone", "tone_key"),
    "rat": ("rating", "rating_key"),
    "pac": ("pace", "pace_key"),
    "dif": ("difficulty", "difficulty_key"),
    "stk": ("stake", "stake_key"),
}
_STEP_TABLES = {
    "uni": _UNIVERSES, "ton": _TONES, "rat": _RATINGS,
    "pac": _PACES, "dif": _DIFFICULTIES, "stk": _STAKES,
}

# Quick-start defaults — what the "🚀 Быстрый старт" button fills in so
# impatient players can skip the whole wizard with one tap.
_QUICKSTART_DEFAULTS = {
    "universe": "🏰 Классическое фэнтези", "universe_key": "fantasy",
    "tone":     "🦸 Эпическая",           "tone_key":     "epic",
    "rating":   "16",                      "rating_key":   "16",
    "pace":     "⚖ Средний",              "pace_key":     "medium",
    "difficulty": "⚖ Норма",              "difficulty_key": "normal",
    "stake":    "💔 Близкий человек, которого надо спасти",
    "stake_key": "loved_one",
}


def _wizard_header(step_idx: int, state: dict) -> str:
    """Render `🎲 Шаг N из M` + a compact summary of the picks so far."""
    head = f"🎲 <b>Визард новой игры</b> — шаг {step_idx + 1} из {_TOTAL_STEPS}"
    picks = []
    for k in _STEP_ORDER[:step_idx]:
        if k == "concept":
            break
        label_field, _ = _STEP_FIELDS[k]
        val = state.get(label_field)
        if val:
            picks.append(f"• {val}")
    if picks:
        head += "\n\n<i>" + "\n".join(picks) + "</i>"
    return head


async def _send_step(target, step_code: str, state: dict, *, edit: bool = True):
    """Render a wizard step. `target` is the Message to send/edit."""
    if step_code == "concept":
        await _send_concept_prompt(target, state, edit=edit)
        return
    title, table, cols = _STEP_TITLES[step_code]
    step_idx = _STEP_ORDER.index(step_code)
    body = f"{_wizard_header(step_idx, state)}\n\n{title}"
    kb = _onboarding_kb(step_code, table, cols=cols)
    if edit:
        try:
            await target.edit_text(body, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await target.answer(body, reply_markup=kb, parse_mode="HTML")


async def _send_concept_prompt(target, state: dict, *, edit: bool = True):
    body = (
        f"{_wizard_header(_STEP_ORDER.index('concept'), state)}\n\n"
        f"📖 Теперь расскажи о персонаже <b>одним сообщением</b>: "
        f"кто он, откуда, что его ведёт.\n\n"
        f"<i>Примеры:</i>\n"
        f" • <i>«Нетраннер-соло, ищет пропавшую сестру в Найт-Сити»</i>\n"
        f" • <i>«Бард-бродяга, проигравший фамильную лютню в карты»</i>\n"
        f" • <i>«Бывший имперский следователь, охотится за артефактом»</i>\n\n"
        f"<i>Или короче — пара слов тоже сойдёт, ГМ дофантазирует.</i>"
    )
    if edit:
        try:
            await target.edit_text(body, parse_mode="HTML")
            return
        except Exception:
            pass
    await target.answer(body, parse_mode="HTML")


async def _load_state(gs) -> dict:
    raw = (gs.onboarding_state_json or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def _save_state(gs, state: dict) -> None:
    gs.onboarding_state_json = json.dumps(state, ensure_ascii=False)


async def _start_wizard(target, game: GameService, db: AsyncSession, user_obj):
    user = await game.get_or_create_user(db, user_obj.id, user_obj.username)
    gs = await game.ensure_session(db, user)
    await _save_state(gs, {"step_code": "uni"})
    gs.turn_number = 0
    gs.last_options_json = "[]"
    await _send_step(target, "uni", {}, edit=False)


@router.message(Command("onboarding"))
async def cmd_onboarding(message: Message, game: GameService, db: AsyncSession) -> None:
    await _start_wizard(message, game, db, message.from_user)


@router.callback_query(F.data == "menu:onboarding")
async def on_menu_onboarding(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    await _start_wizard(cb.message, game, db, cb.from_user)


@router.callback_query(F.data == "onb:back")
async def on_onboarding_back(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer()
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    state = await _load_state(gs)
    cur = state.get("step_code", "uni")
    if cur in _STEP_ORDER:
        idx = max(0, _STEP_ORDER.index(cur) - 1)
    else:
        idx = 0
    new_step = _STEP_ORDER[idx]
    # Clear the field for the step we're going back to so the player can re-pick.
    if new_step in _STEP_FIELDS:
        label_field, key_field = _STEP_FIELDS[new_step]
        state.pop(label_field, None)
        state.pop(key_field, None)
    state["step_code"] = new_step
    await _save_state(gs, state)
    await _send_step(cb.message, new_step, state, edit=True)


@router.callback_query(F.data == "onb:cancel")
async def on_onboarding_cancel(cb: CallbackQuery, game: GameService, db: AsyncSession) -> None:
    await cb.answer("Отменено.")
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    gs.onboarding_state_json = ""
    try:
        await cb.message.edit_text(
            "Визард отменён. Опиши героя одним сообщением или снова /onboarding."
        )
    except Exception:
        pass


@router.callback_query(F.data == "onb:quick")
async def on_onboarding_quick(
    cb: CallbackQuery, game: GameService, db: AsyncSession,
) -> None:
    """Skip the entire wizard with sensible defaults — jump straight to
    'describe your character' so impatient players can play in 2 taps."""
    await cb.answer("Быстрый старт 🚀")
    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    state = dict(_QUICKSTART_DEFAULTS)
    state["step_code"] = "concept"
    await _save_state(gs, state)
    await _send_step(cb.message, "concept", state, edit=True)


@router.callback_query(F.data.regexp(r"^onb:(uni|ton|rat|pac|dif|stk):"))
async def on_onboarding_pick(
    cb: CallbackQuery, game: GameService, db: AsyncSession,
) -> None:
    """Generic step handler: writes the chosen value into state, advances to
    the next step. Value of `_skip` keeps the default unset.
    """
    await cb.answer()
    parts = cb.data.split(":", 2)
    if len(parts) != 3:
        return
    _, step_code, value_key = parts
    if step_code not in _STEP_FIELDS:
        return

    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    state = await _load_state(gs)

    if value_key != "_skip":
        label = _label_for(_STEP_TABLES[step_code], value_key)
        label_field, key_field = _STEP_FIELDS[step_code]
        state[label_field] = label
        state[key_field] = value_key

    cur_idx = _STEP_ORDER.index(step_code)
    next_step = _STEP_ORDER[cur_idx + 1] if cur_idx + 1 < len(_STEP_ORDER) else "concept"
    state["step_code"] = next_step
    await _save_state(gs, state)
    await _send_step(cb.message, next_step, state, edit=True)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "ℹ <b>Справка</b>\n\n"
        "/start — продолжить или начать заново\n"
        "/stats — карточка персонажа\n"
        "/inventory — инвентарь с формулами урона\n"
        "/quest — активные квесты\n"
        "/shop — товары ближайшего торговца\n"
        "/buy &lt;item&gt; [qty] — купить\n"
        "/sell &lt;item&gt; [qty] — продать\n"
        "/craft [рецепт] — список или крафт\n"
        "/abilities — список способностей\n"
        "/use &lt;название&gt; — применить способность\n"
        "/quests — журнал квестов\n"
        "/companions — напарники\n"
        "/levelup — выбрать перк уровня\n"
        "/combat — статус боя (раунд, инициатива)\n"
        "/carry — нагрузка и грузоподъёмность\n"
        "/attunement — настроенные предметы\n"
        "/attune &lt;item&gt; — настроиться на предмет\n"
        "/unattune &lt;item&gt; — снять настройку\n"
        "/hint — подсказка GM\n"
        "/rest — короткий или длинный отдых\n"
        "/onboarding — визард новой игры\n"
        "/new — новая игра (очищает сцену)\n\n"
        "В любой момент можно задать вопрос GM: напиши <code>ГМ: ...</code>.\n"
        "Пример: <i>«ГМ: что такое преимущество?»</i>",
        parse_mode="HTML",
    )


@router.message(F.text)
async def on_text(message: Message, game: GameService, db: AsyncSession) -> None:
    user = await game.get_or_create_user(db, message.from_user.id, message.from_user.username)
    gs = await game.ensure_session(db, user)
    text = message.text.strip()

    if gs.turn_number == 0:
        # If the guided wizard was used, onboarding_state_json holds the
        # universe + tone + rating + pace + difficulty picks. Build a rich
        # concept block so initialize_story passes them all to the LLM.
        # KEEP the state around afterwards (just drop the step_code) so
        # build_context can replay tone/rating/pace into EVERY system
        # prompt — without that the LLM forgets the vibe by turn 3.
        concept = text
        onb_raw = (gs.onboarding_state_json or "").strip()
        if onb_raw:
            try:
                onb = json.loads(onb_raw)
            except Exception:
                onb = {}
            if isinstance(onb, dict) and onb:
                bits = []
                if onb.get("universe"):
                    bits.append(f"Вселенная: {onb['universe']}")
                if onb.get("tone"):
                    bits.append(f"Тональность: {onb['tone']}")
                if onb.get("rating"):
                    bits.append(f"Рейтинг: {onb['rating']}+")
                if onb.get("pace"):
                    bits.append(f"Темп: {onb['pace']}")
                if onb.get("difficulty"):
                    bits.append(f"Сложность: {onb['difficulty']}")
                if onb.get("stake"):
                    bits.append(f"Личная ставка: {onb['stake']}")
                if bits:
                    concept = " | ".join(bits) + f"\nПерсонаж: {text}"
                # Drop transient wizard cursor but keep prefs (incl. stake)
                # alive in onboarding_state_json so build_context can
                # replay them into every future system prompt.
                onb.pop("step_code", None)
                gs.onboarding_state_json = json.dumps(onb, ensure_ascii=False)
        async with typing_status(message.bot, message.chat.id):
            out = await game.initialize_story(db, user, concept)
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
