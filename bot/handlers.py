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
# Kept simple: a small 3-step wizard backed by the user's existing
# GameSession.last_options_json as transient state storage. We avoid
# importing aiogram.fsm to stay drop-in compatible with the current
# middleware. Steps: universe → style → concept text → initialize_story.

_UNIVERSES = [
    ("fantasy", "🏰 Фэнтези"),
    ("cyberpunk", "🌆 Киберпанк"),
    ("postapoc", "☢ Постапокалипсис"),
    ("space", "🚀 Космоопера"),
    ("horror", "👻 Хоррор"),
    ("noir", "🕵 Нуар-детектив"),
]
_STYLES = [
    ("serious", "Серьёзный"),
    ("dark", "Мрачный"),
    ("humor", "С юмором"),
    ("epic", "Эпический"),
    ("gritty", "Жёсткий"),
]


def _onboarding_kb_universes():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for i in range(0, len(_UNIVERSES), 2):
        row = _UNIVERSES[i:i + 2]
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"onb:uni:{key}")
            for key, label in row
        ])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="onb:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _onboarding_kb_styles(universe_key: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for i in range(0, len(_STYLES), 2):
        row = _STYLES[i:i + 2]
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"onb:sty:{universe_key}:{key}")
            for key, label in row
        ])
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="onb:restart")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("onboarding"))
async def cmd_onboarding(message: Message) -> None:
    await message.answer(
        "🎲 <b>Визард новой игры</b> — шаг 1 из 3\n\n"
        "Выбери вселенную:",
        reply_markup=_onboarding_kb_universes(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:onboarding")
async def on_menu_onboarding(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(
        "🎲 <b>Визард новой игры</b> — шаг 1 из 3\n\nВыбери вселенную:",
        reply_markup=_onboarding_kb_universes(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "onb:restart")
async def on_onboarding_restart(cb: CallbackQuery) -> None:
    await cb.answer()
    try:
        await cb.message.edit_text(
            "🎲 <b>Визард новой игры</b> — шаг 1 из 3\n\nВыбери вселенную:",
            reply_markup=_onboarding_kb_universes(),
            parse_mode="HTML",
        )
    except Exception:
        await cb.message.answer(
            "🎲 <b>Визард новой игры</b> — шаг 1 из 3\n\nВыбери вселенную:",
            reply_markup=_onboarding_kb_universes(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "onb:cancel")
async def on_onboarding_cancel(cb: CallbackQuery) -> None:
    await cb.answer("Отменено.")
    try:
        await cb.message.edit_text("Визард отменён. Можешь описать героя одним сообщением или снова /onboarding.")
    except Exception:
        pass


@router.callback_query(F.data.startswith("onb:uni:"))
async def on_onboarding_universe(cb: CallbackQuery) -> None:
    await cb.answer()
    key = cb.data.split(":")[-1]
    label = next((lbl for k, lbl in _UNIVERSES if k == key), key)
    try:
        await cb.message.edit_text(
            f"🎲 <b>Визард</b> — шаг 2 из 3\n\n"
            f"Вселенная: <b>{label}</b>\n\nТеперь выбери стиль повествования:",
            reply_markup=_onboarding_kb_styles(key),
            parse_mode="HTML",
        )
    except Exception:
        await cb.message.answer(
            f"🎲 <b>Визард</b> — шаг 2 из 3\n\nВселенная: <b>{label}</b>\nСтиль:",
            reply_markup=_onboarding_kb_styles(key),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("onb:sty:"))
async def on_onboarding_style(
    cb: CallbackQuery, game: GameService, db: AsyncSession,
) -> None:
    _, _, uni_key, sty_key = cb.data.split(":")
    uni_label = next((lbl for k, lbl in _UNIVERSES if k == uni_key), uni_key)
    sty_label = next((lbl for k, lbl in _STYLES if k == sty_key), sty_key)

    user = await game.get_or_create_user(db, cb.from_user.id, cb.from_user.username)
    gs = await game.ensure_session(db, user)
    # Stash wizard answers in a dedicated column so they don't collide with
    # player-facing option lists. Cleared by `on_text` right after the
    # player sends their character concept.
    gs.onboarding_state_json = json.dumps({
        "universe": uni_label, "universe_key": uni_key,
        "style": sty_label, "style_key": sty_key,
    }, ensure_ascii=False)
    gs.turn_number = 0  # force initialize_story on the next text
    gs.last_options_json = "[]"

    await cb.answer()
    try:
        await cb.message.edit_text(
            f"🎲 <b>Визард</b> — шаг 3 из 3\n\n"
            f"Вселенная: <b>{uni_label}</b>\n"
            f"Стиль: <b>{sty_label}</b>\n\n"
            f"Теперь опиши персонажа <b>одним сообщением</b>: кто он, чем занимается, что его ведёт.\n"
            f"Примеры:\n"
            f" • <i>«Нетраннер-соло, ищет пропавшую сестру»</i>\n"
            f" • <i>«Бывший паладин, отрёкшийся от ордена»</i>",
            parse_mode="HTML",
        )
    except Exception:
        await cb.message.answer("Теперь опиши персонажа одним сообщением.", parse_mode="HTML")


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
        # universe + style choices. Prepend them to the concept so
        # `initialize_story` and the LLM see the intended setting.
        concept = text
        onb_raw = (gs.onboarding_state_json or "").strip()
        if onb_raw:
            try:
                onb = json.loads(onb_raw)
            except Exception:
                onb = {}
            if isinstance(onb, dict) and onb:
                concept = (
                    f"Вселенная: {onb.get('universe', '')}. "
                    f"Стиль: {onb.get('style', '')}. "
                    f"Персонаж: {text}"
                )
            gs.onboarding_state_json = ""
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
