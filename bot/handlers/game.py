"""Main gameplay loop: single-pass — one Gemini call per turn."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import OnboardingState
from bot.services import game_engine as engine
from bot.services.gemini import GeminiError, GameResponse, generate_narrative, generate_structured
from bot.services.memory import build_context, maybe_summarize, save_episodic_memory
from bot.services.personalization import maybe_run_deep_analysis, track_action_choice, track_interaction
from bot.services.prompt_builder import game_turn_prompt, system_prompt
from bot.services.user_service import ensure_character, ensure_session, get_or_create_user, reset_game
from bot.utils.formatters import (
    compact_stat_bar,
    format_ability_card,
    format_character_sheet,
    format_inventory,
    format_quest,
    md_to_html,
    truncate_for_telegram,
)
from bot.utils.i18n import t
from bot.utils.keyboards import (
    abilities_list_keyboard,
    ability_detail_keyboard,
    actions_keyboard,
    game_menu_keyboard,
    inventory_categories_keyboard,
    rest_keyboard,
)

log = logging.getLogger(__name__)
router = Router(name="game")


def _default_actions(lang: str) -> list[str]:
    if lang == "ru":
        return ["Осмотреться", "Поговорить", "Исследовать", "Проверить инвентарь"]
    return ["Look around", "Talk to someone", "Explore", "Check inventory"]


async def _typing(event: Message | CallbackQuery) -> None:
    chat_id = event.chat.id if isinstance(event, Message) else event.message.chat.id
    bot = event.bot if isinstance(event, Message) else event.message.bot
    await bot.send_chat_action(chat_id, ChatAction.TYPING)


# ---- Slash commands ----

@router.message(Command("stats"))
async def cmd_stats(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if not user.character:
        await message.answer("No active game. /start")
        return
    gs = await ensure_session(user, db)
    cur = gs.currency_name or ""
    await message.answer(format_character_sheet(user.character, user.language, cur), parse_mode="HTML")


@router.message(Command("quest"))
async def cmd_quest(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if user.onboarding_state != OnboardingState.PLAYING:
        return
    gs = await ensure_session(user, db)
    await message.answer(format_quest(gs.current_quest, gs.current_location), parse_mode="HTML")


@router.message(Command("debug"))
async def cmd_debug(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if not user.character:
        await message.answer("No active game.")
        return
    gs = await ensure_session(user, db)
    debug_info = {
        "state": user.onboarding_state.value,
        "tier": user.content_tier.value,
        "lang": user.language,
        "char": user.character.to_sheet_dict(),
        "session": gs.to_state_dict(),
        "msgs": gs.message_count,
    }
    text = f"<pre>{json.dumps(debug_info, indent=2, ensure_ascii=False)[:3800]}</pre>"
    await message.answer(text, parse_mode="HTML")


# ---- Game menu ----

@router.callback_query(F.data.startswith("gamemenu:"))
async def on_game_menu(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    action = cb.data.split(":")[1]

    if action == "open":
        await cb.message.edit_reply_markup(reply_markup=game_menu_keyboard(user.language))
        await cb.answer()
        return

    if action == "close":
        gs = await ensure_session(user, db)
        saved_actions = gs.last_actions or None
        saved_styles = gs.last_action_styles or None
        combat_data = None
        if gs.in_combat:
            char = await ensure_character(user, db)
            combat_data = {"inventory": char.inventory or [], "abilities": char.abilities or []}
        await cb.message.edit_reply_markup(
            reply_markup=actions_keyboard(saved_actions, user.language,
                                          styles=saved_styles, combat_data=combat_data)
        )
        await cb.answer()
        return

    if action == "stats":
        char = await ensure_character(user, db)
        gs = await ensure_session(user, db)
        cur = gs.currency_name or ""
        await cb.message.answer(format_character_sheet(char, user.language, cur), parse_mode="HTML")
        await cb.answer()
        return

    if action == "inv":
        char = await ensure_character(user, db)
        gs = await ensure_session(user, db)
        cur = gs.currency_name or ""
        text = format_inventory(char, user.language, cur)
        kb = inventory_categories_keyboard(char.inventory, user.language) if char.inventory else None
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await cb.answer()
        return

    if action == "abilities":
        char = await ensure_character(user, db)
        abilities = char.abilities
        if not abilities:
            msg = "У тебя пока нет способностей." if user.language == "ru" else "You don't have any abilities yet."
            await cb.message.answer(msg, parse_mode="HTML")
            await cb.answer()
            return
        header = "⚡ <b>Способности</b>\n\n<i>Нажми, чтобы узнать подробности:</i>" if user.language == "ru" \
            else "⚡ <b>Abilities</b>\n\n<i>Tap to see details:</i>"
        await cb.message.answer(
            header, parse_mode="HTML",
            reply_markup=abilities_list_keyboard(abilities, user.language),
        )
        await cb.answer()
        return

    if action == "quest":
        gs = await ensure_session(user, db)
        await cb.message.answer(
            format_quest(gs.current_quest, gs.current_location), parse_mode="HTML"
        )
        await cb.answer()
        return

    if action == "location":
        gs = await ensure_session(user, db)
        await cb.message.answer(
            t("LOCATION_INFO", user.language, location=gs.current_location), parse_mode="HTML"
        )
        await cb.answer()
        return

    if action == "locinfo":
        gs = await ensure_session(user, db)
        desc = gs.location_description
        loc = gs.current_location or ("Неизвестно" if user.language == "ru" else "Unknown")

        if not desc:
            wait_msg = "📍 <i>Осматриваю локацию...</i>" if user.language == "ru" else "📍 <i>Scanning location...</i>"
            await cb.message.answer(wait_msg, parse_mode="HTML")
            char = await ensure_character(user, db)
            loc_prompt = (
                f"Describe the location '{loc}' for the player. "
                f"Character: {char.name}, {char.char_class}. Context: {gs.current_quest or 'exploring'}.\n"
                f"Write 3-5 sentences in {user.language}:\n"
                f"- Physical layout: room size, shape, corridors/open space\n"
                f"- ALL exits: doors, windows, hatches, vents, passages — and where they seem to lead\n"
                f"- Interactive objects: consoles, crates, cover, machinery, containers, weapons, furniture\n"
                f"- Hazards/opportunities: explosive containers, electrical panels, toxic materials, fire sources\n"
                f"- Atmosphere: lighting, sounds, smells\n"
                f"This is a tactical briefing, not prose. Be specific and useful. Use HTML formatting."
            )
            try:
                desc = await generate_narrative(
                    loc_prompt, content_tier=user.content_tier.value, light=True,
                )
                gs.location_description = desc
            except Exception:
                desc = ""

        if desc:
            text = f"📍 <b>{loc}</b>\n\n{md_to_html(desc)}"
        else:
            text = f"📍 <b>{loc}</b>"
        await cb.message.answer(truncate_for_telegram(text, 3800), parse_mode="HTML")
        await cb.answer()
        return

    if action == "rest":
        await cb.message.edit_reply_markup(reply_markup=rest_keyboard(user.language))
        await cb.answer()
        return

    if action == "short_rest":
        char = await ensure_character(user, db)
        result = engine.short_rest(char, lang=user.language)
        await cb.message.answer(f"☀️ {result}", parse_mode="HTML")
        await cb.answer()
        return

    if action == "long_rest":
        char = await ensure_character(user, db)
        result = engine.long_rest(char, lang=user.language)
        await cb.message.answer(f"🌙 {result}", parse_mode="HTML")
        await cb.answer()
        return

    if action == "inspect":
        await _typing(cb)
        char = await ensure_character(user, db)
        gs = await ensure_session(user, db)
        ctx = await build_context(user, char, gs, db)
        sys_instr = system_prompt(user.language, user.content_tier.value)
        prompt = (
            f"{ctx}\n\nThe player wants a tactical assessment of the current situation. "
            f"Describe what they see, hear, smell. Mention any threats, opportunities, "
            f"or notable details. Be specific. Write in {user.language}. Use HTML formatting."
        )
        try:
            text = await generate_narrative(
                prompt, content_tier=user.content_tier.value, system_instruction=sys_instr, light=True,
            )
            text = md_to_html(text)
            await cb.message.answer(truncate_for_telegram(f"🔎 {text}", 3800), parse_mode="HTML")
        except Exception as e:
            log.exception("Inspect failed")
            err = e.user_message(user.language) if isinstance(e, GeminiError) else t("ERROR", user.language)
            await cb.message.answer(err, parse_mode="HTML")
        await cb.answer()
        return

    if action == "askgm":
        await _typing(cb)
        char = await ensure_character(user, db)
        gs = await ensure_session(user, db)
        ctx = await build_context(user, char, gs, db)
        sys_instr = system_prompt(user.language, user.content_tier.value)
        prompt = (
            f"{ctx}\n\nThe player asks the GM for advice. Provide helpful mechanical tips: "
            f"suggest what skills/items might be useful, remind them of abilities they can use, "
            f"hint at possible strategies. Don't reveal hidden information. "
            f"Write in {user.language}. Use HTML formatting."
        )
        try:
            text = await generate_narrative(
                prompt, content_tier=user.content_tier.value, system_instruction=sys_instr, light=True,
            )
            text = md_to_html(text)
            await cb.message.answer(truncate_for_telegram(f"❓ {text}", 3800), parse_mode="HTML")
        except Exception as e:
            log.exception("Ask GM failed")
            err = e.user_message(user.language) if isinstance(e, GeminiError) else t("ERROR", user.language)
            await cb.message.answer(err, parse_mode="HTML")
        await cb.answer()
        return

    if action == "newgame":
        await reset_game(user, db)
        await cb.message.answer("/start", parse_mode="HTML")
        await cb.answer()
        return

    if action == "help":
        await cb.message.answer(t("MENU_HELP", user.language), parse_mode="HTML")
        await cb.answer()
        return

    await cb.answer()


# ---- Abilities viewer (#18) ----

@router.callback_query(F.data.startswith("ability:select:"))
async def on_ability_select(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)
    idx = int(cb.data.split(":")[2])
    abilities = char.abilities
    if idx >= len(abilities):
        await cb.answer("Not found", show_alert=True)
        return
    text = format_ability_card(abilities[idx], user.language)
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=ability_detail_keyboard(idx, user.language))
    await cb.answer()


@router.callback_query(F.data == "ability:back")
async def on_ability_back(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)
    abilities = char.abilities
    if not abilities:
        await cb.answer()
        return
    header = "⚡ <b>Способности</b>\n\n<i>Нажми, чтобы узнать подробности:</i>" if user.language == "ru" \
        else "⚡ <b>Abilities</b>\n\n<i>Tap to see details:</i>"
    await cb.message.edit_text(
        header, parse_mode="HTML",
        reply_markup=abilities_list_keyboard(abilities, user.language),
    )
    await cb.answer()


# ---- Inline button actions ----

@router.callback_query(F.data.startswith("act:"))
async def on_action_button(cb: CallbackQuery, db: AsyncSession) -> None:
    action_text = cb.data[4:]
    await cb.answer()
    await _typing(cb)
    await _process_player_action(cb.message, cb.from_user.id, cb.from_user.username, action_text, db)


# ---- Death save / restart callbacks ----

@router.callback_query(F.data == "deathsave")
async def on_death_save(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)
    gs = await ensure_session(user, db)
    if char.current_hp > 0:
        await cb.answer()
        return
    await _handle_death_save(cb.message, user, char, gs, db)
    await cb.answer()


@router.callback_query(F.data == "restart")
async def on_restart(cb: CallbackQuery, db: AsyncSession) -> None:
    await cb.answer()
    await cb.message.answer("/start — начни новое приключение")


# ---- #10: Combat quick buttons ----

@router.callback_query(F.data.startswith("cbt:"))
async def on_combat_button(cb: CallbackQuery, db: AsyncSession) -> None:
    parts = cb.data.split(":")
    btn_type = parts[1]
    idx = int(parts[2])

    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    char = await ensure_character(user, db)
    lang = user.language

    if btn_type == "w":
        inv = char.inventory or []
        if idx >= len(inv):
            await cb.answer("Not found", show_alert=True)
            return
        name = inv[idx].get("name", "???")
        action_text = f"Атакую {name}" if lang == "ru" else f"I attack with {name}"
    elif btn_type == "p":
        inv = char.inventory or []
        if idx >= len(inv):
            await cb.answer("Not found", show_alert=True)
            return
        name = inv[idx].get("name", "???")
        action_text = f"Использую {name}" if lang == "ru" else f"I use {name}"
    elif btn_type == "a":
        abilities = char.abilities or []
        if idx >= len(abilities):
            await cb.answer("Not found", show_alert=True)
            return
        name = abilities[idx].get("name", "???")
        action_text = f"Использую способность {name}" if lang == "ru" else f"I use ability {name}"
    else:
        await cb.answer()
        return

    await cb.answer()
    await _typing(cb)
    await _process_player_action(cb.message, cb.from_user.id, cb.from_user.username, action_text, db)


# ---- Meta-question detection (#2) ----

_GM_PREFIXES = ("гм:", "гм,", "gm:", "gm,", "мастер:", "мастер,", "dm:", "dm,")
_GM_PATTERNS_RU = ("а что значит", "а как работает", "а почему", "объясни", "расскажи про механик",
                   "что такое", "как мне", "подскажи", "напомни правил", "сколько у меня",
                   "а что за", "уважаемый гм", "уважаемый мастер", "вопрос к мастер")
_GM_PATTERNS_EN = ("what does", "how does", "what is", "explain", "remind me", "how do i",
                   "tell me about mechanic", "what are my", "question for")


def _is_meta_question(text: str) -> bool:
    low = text.lower().strip()
    for prefix in _GM_PREFIXES:
        if low.startswith(prefix):
            return True
    for p in _GM_PATTERNS_RU:
        if low.startswith(p):
            return True
    for p in _GM_PATTERNS_EN:
        if low.startswith(p):
            return True
    return False


async def _handle_meta_question(message: Message, user, db: AsyncSession) -> None:
    await _typing(message)
    char = await ensure_character(user, db)
    gs = await ensure_session(user, db)
    ctx = await build_context(user, char, gs, db)
    sys_instr = system_prompt(user.language, user.content_tier.value)
    question = message.text.strip()
    for prefix in _GM_PREFIXES:
        if question.lower().startswith(prefix):
            question = question[len(prefix):].strip()
            break
    prompt = (
        f"{ctx}\n\nThe player asks a META-QUESTION (out of game, about mechanics/rules/character): "
        f"\"{question}\"\n\n"
        f"Answer helpfully about game mechanics, rules, character abilities, or strategy. "
        f"Do NOT advance the story. Do NOT generate dice rolls. "
        f"Write in {user.language}. Use HTML formatting. Be concise (2-4 sentences)."
    )
    try:
        text = await generate_narrative(
            prompt, content_tier=user.content_tier.value, system_instruction=sys_instr, light=True,
        )
        text = md_to_html(text)
        label = "ГМ" if user.language == "ru" else "GM"
        await message.answer(
            truncate_for_telegram(f"({label}: {text})", 3800),
            parse_mode="HTML",
        )
    except Exception as e:
        log.exception("Meta-question failed")
        err = e.user_message(user.language) if isinstance(e, GeminiError) else t("ERROR", user.language)
        await message.answer(err, parse_mode="HTML")


# ---- Free text ----

@router.message(F.text)
async def on_game_text(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)

    if user.onboarding_state != OnboardingState.PLAYING:
        from bot.handlers.start import handle_onboarding_text
        handled = await handle_onboarding_text(message, user, db)
        if not handled:
            hint = "👆 Нажми кнопку выше" if user.language == "ru" else "👆 Please press a button above"
            await message.answer(hint)
        return

    if _is_meta_question(message.text):
        await _handle_meta_question(message, user, db)
        return

    await _typing(message)
    await _process_player_action(message, message.from_user.id, message.from_user.username,
                                  message.text.strip(), db)


# ---- Progressive status messages (#19) ----

_PROGRESS_POOL_RU = [
    [
        "🎲 <i>Бросаю кости судьбы...</i>",
        "🎲 <i>Сверяюсь с правилами...</i>",
        "🎲 <i>Прикидываю расклад...</i>",
        "🎲 <i>Кости катятся по столу...</i>",
        "🎲 <i>Раскладываю карты...</i>",
        "🎲 <i>Обрабатываю ход...</i>",
        "🎲 <i>Перелистываю бестиарий...</i>",
        "🎲 <i>Сверяюсь с картой...</i>",
    ],
    [
        "🤔 <i>Плету интригу...</i>",
        "🤔 <i>Тасую карты судьбы...</i>",
        "🤔 <i>Советуюсь с богами хаоса...</i>",
        "🤔 <i>Прорабатываю последствия...</i>",
        "🤔 <i>Взвешиваю исходы...</i>",
        "🤔 <i>Вычисляю вероятности...</i>",
        "🤔 <i>Думаю, что бы сделал злодей...</i>",
        "🤔 <i>Сюжет густеет...</i>",
        "🤔 <i>Ветви судьбы переплетаются...</i>",
        "🤔 <i>NPC готовят ответ...</i>",
    ],
    [
        "📝 <i>Записываю в хроники...</i>",
        "📝 <i>Чернила сохнут на пергаменте...</i>",
        "📝 <i>Летописец скрипит пером...</i>",
        "📝 <i>Пишу историю...</i>",
        "📝 <i>Формирую нарратив...</i>",
        "📝 <i>Добавляю атмосферу...</i>",
        "📝 <i>Мир оживает на бумаге...</i>",
        "📝 <i>Описываю сцену...</i>",
    ],
    [
        "⚡ <i>Ещё чуть-чуть...</i>",
        "⚡ <i>Судьба почти решена...</i>",
        "⚡ <i>Звёзды почти сошлись...</i>",
        "⚡ <i>Финальные штрихи...</i>",
        "⚡ <i>Дописываю последнюю строку...</i>",
        "⚡ <i>Почти готово...</i>",
        "⚡ <i>Осталось совсем немного...</i>",
        "⚡ <i>Шлифую детали...</i>",
    ],
]

_PROGRESS_POOL_EN = [
    [
        "🎲 <i>Rolling the dice of fate...</i>",
        "🎲 <i>Consulting the rulebook...</i>",
        "🎲 <i>Weighing the odds...</i>",
        "🎲 <i>Dice clatter on the table...</i>",
        "🎲 <i>Shuffling the deck...</i>",
        "🎲 <i>Processing your move...</i>",
        "🎲 <i>Flipping through the bestiary...</i>",
        "🎲 <i>Checking the map...</i>",
    ],
    [
        "🤔 <i>Weaving the plot...</i>",
        "🤔 <i>Shuffling fate's cards...</i>",
        "🤔 <i>Consulting the chaos gods...</i>",
        "🤔 <i>Calculating consequences...</i>",
        "🤔 <i>Weighing outcomes...</i>",
        "🤔 <i>Computing probabilities...</i>",
        "🤔 <i>Wondering what the villain would do...</i>",
        "🤔 <i>The plot thickens...</i>",
        "🤔 <i>Threads of destiny intertwine...</i>",
        "🤔 <i>NPCs preparing a response...</i>",
    ],
    [
        "📝 <i>Writing in the chronicles...</i>",
        "📝 <i>Ink drying on parchment...</i>",
        "📝 <i>The scribe's quill scratches...</i>",
        "📝 <i>Crafting the story...</i>",
        "📝 <i>Shaping the narrative...</i>",
        "📝 <i>Adding atmosphere...</i>",
        "📝 <i>The world comes alive on paper...</i>",
        "📝 <i>Describing the scene...</i>",
    ],
    [
        "⚡ <i>Almost there...</i>",
        "⚡ <i>Fate nearly decided...</i>",
        "⚡ <i>Stars almost aligned...</i>",
        "⚡ <i>Final touches...</i>",
        "⚡ <i>Writing the last line...</i>",
        "⚡ <i>Nearly done...</i>",
        "⚡ <i>Just a moment more...</i>",
        "⚡ <i>Polishing details...</i>",
    ],
]


def _pick_progress_step(pool: list[list[str]], stage: int) -> str:
    stage = min(stage, len(pool) - 1)
    return random.choice(pool[stage])


async def _keep_typing_with_progress(
    bot, chat_id: int, progress_msg: Message | None,
    stop_event: asyncio.Event, lang: str = "ru",
) -> None:
    pool = _PROGRESS_POOL_RU if lang == "ru" else _PROGRESS_POOL_EN
    stage = 0
    elapsed = 0.0
    interval = 3.5
    stage_thresholds = [0.0, 3.5, 7.0, 12.0]

    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            elapsed += interval
            new_stage = stage
            for i, thresh in enumerate(stage_thresholds):
                if elapsed >= thresh:
                    new_stage = i
            if new_stage != stage and progress_msg:
                stage = new_stage
                text = _pick_progress_step(pool, stage)
                try:
                    await progress_msg.edit_text(text, parse_mode="HTML")
                except Exception:
                    pass


# ---- Death saves ----

def _death_save_keyboard(lang: str) -> InlineKeyboardMarkup:
    label = "🎲 Бросок спасения от смерти" if lang == "ru" else "🎲 Death Saving Throw"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data="deathsave", style="danger")],
    ])


def _dead_keyboard(lang: str) -> InlineKeyboardMarkup:
    label = "🔄 /start — новое приключение" if lang == "ru" else "🔄 /start — new adventure"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data="restart")],
    ])


async def _handle_death_save(
    reply_target: Message, user, char, gs, db: AsyncSession,
) -> None:
    lang = user.language
    ds = engine.death_saving_throw(char)
    text = ds.display_localized(lang)

    if ds.stabilized:
        char.current_hp = 0
        gs.in_combat = False
        text += "\n\n" + t("STABILIZED", lang, name=char.name)
        text += f"\n\n<code>{compact_stat_bar(char, lang, gs.currency_name)}</code>"
        kb = actions_keyboard(
            ["Осмотреться" if lang == "ru" else "Look around"],
            lang,
        )
    elif ds.dead:
        text += "\n\n" + t("DEATH", lang, name=char.name)
        kb = _dead_keyboard(lang)
    else:
        text += f"\n\n<code>{compact_stat_bar(char, lang, gs.currency_name)}</code>"
        kb = _death_save_keyboard(lang)

    await reply_target.answer(text, parse_mode="HTML", reply_markup=kb)


# ---- Core game loop (single-pass) ----

async def _process_player_action(
    reply_target: Message, telegram_id: int, username: str | None,
    player_action: str, db: AsyncSession,
) -> None:
    user = await get_or_create_user(telegram_id, username, db)
    if user.onboarding_state != OnboardingState.PLAYING:
        return
    char = await ensure_character(user, db)
    gs = await ensure_session(user, db)

    if char.current_hp <= 0:
        await _handle_death_save(reply_target, user, char, gs, db)
        return

    start_time = time.monotonic()
    track_interaction(user, player_action)
    track_action_choice(user, player_action)
    gs.append_message("user", player_action)
    gs.turn_number += 1

    sys_prompt = system_prompt(user.language, user.content_tier.value)
    context = await build_context(user, char, gs, db)

    lang = user.language
    pool = _PROGRESS_POOL_RU if lang == "ru" else _PROGRESS_POOL_EN
    first_msg = _pick_progress_step(pool, 0)
    try:
        progress_msg = await reply_target.answer(first_msg, parse_mode="HTML")
    except Exception:
        progress_msg = None

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _keep_typing_with_progress(
            reply_target.bot, reply_target.chat.id, progress_msg, stop_typing, lang
        )
    )

    try:
        decision: GameResponse = await generate_structured(
            game_turn_prompt(context, player_action, language=user.language),
            GameResponse, content_tier=user.content_tier.value,
            max_tokens=4096,
            system_instruction=sys_prompt,
        )
    except Exception as e:
        stop_typing.set()
        await typing_task
        log.exception("Game turn failed")
        err_text = e.user_message(user.language) if isinstance(e, GeminiError) else t("ERROR", user.language)
        err_text += "\n\n<i>" + ("Прогресс сохранён." if lang == "ru" else "Progress saved.") + "</i>"
        if progress_msg:
            try:
                await progress_msg.edit_text(err_text, parse_mode="HTML")
                return
            except Exception:
                pass
        await reply_target.answer(err_text, parse_mode="HTML")
        return

    stop_typing.set()
    await typing_task

    # --- Execute mechanics ---
    mechanics_lines: list[str] = []
    any_succeeded = False
    any_failed = False
    had_checks = False

    for sc in decision.skill_checks:
        try:
            r = engine.skill_check(char, sc.skill, sc.dc, sc.advantage, sc.disadvantage)
            mechanics_lines.append(r.display_localized(lang))
            had_checks = True
            if r.success:
                any_succeeded = True
            else:
                any_failed = True
        except Exception:
            log.warning("Skill check failed: %s", sc.skill)

    for st in decision.saving_throws:
        try:
            r = engine.saving_throw(char, st.ability, st.dc, st.advantage, st.disadvantage)
            mechanics_lines.append(r.display_localized(lang))
            had_checks = True
            if r.success:
                any_succeeded = True
            else:
                any_failed = True
        except Exception:
            log.warning("Saving throw failed: %s", st.ability)

    if decision.attack_target_ac and decision.attack_target_ac > 0:
        try:
            atk = engine.make_attack(
                char, decision.attack_target_ac,
                decision.attack_damage_dice or "1d8", decision.attack_ability or "strength", True,
            )
            atk_display = atk.display_localized(lang)
            t_hp = decision.attack_target_hp
            t_max = decision.attack_target_max_hp
            mechanics_lines.append(atk_display)
            had_checks = True
            if atk.hit:
                any_succeeded = True
                if t_hp > 0 and t_max > 0 and atk.damage:
                    remaining = max(0, t_hp - atk.damage)
                    hp_lbl = "HP цели" if lang == "ru" else "Target HP"
                    mechanics_lines.append(f"🎯 {hp_lbl}: <b>{remaining}</b>/{t_max}")
            else:
                if t_hp > 0 and t_max > 0:
                    hp_lbl = "HP цели" if lang == "ru" else "Target HP"
                    mechanics_lines.append(f"🎯 {hp_lbl}: {t_hp}/{t_max}")
            else:
                any_failed = True
        except Exception:
            log.warning("Attack failed: ac=%s dice=%s", decision.attack_target_ac, decision.attack_damage_dice)

    for npc in decision.npc_actions:
        if npc.damage_dice:
            try:
                atk_bonus = npc.attack_bonus if hasattr(npc, 'attack_bonus') else 3
                npc_atk = engine.roll("1d20", modifier=atk_bonus, reason=f"{npc.name}")
                player_ac = char.ac
                npc_hit = npc_atk.natural_20 or npc_atk.total >= player_ac
                ru = lang == "ru"
                nat = npc_atk.nat_tag
                header = (
                    f"🛡 <b>{npc.name}</b> {'атакует' if ru else 'attacks'} "
                    f"→ {'твой' if ru else 'your'} AC {player_ac}"
                )
                roll_line = (
                    f"🎲 {'Бросок' if ru else 'Roll'}: <b>{npc_atk.total}</b> "
                    f"({npc_atk.detail}){nat}"
                )
                if npc_hit:
                    dice = npc.damage_dice
                    if npc_atk.natural_20:
                        parts_d = dice.split("d")
                        cnt = int(parts_d[0]) * 2
                        dice = f"{cnt}d{parts_d[1]}"
                    dmg = engine.roll(dice, reason=f"{npc.name}")
                    hp_line = engine.apply_damage_verbose(char, dmg.total, lang)
                    if npc_atk.natural_20:
                        hit_tag = f"💥 <b>{'КРИТ!' if ru else 'CRIT!'}</b>"
                    else:
                        hit_tag = f"✅ <b>{'Попадание!' if ru else 'Hit!'}</b>"
                    dmg_line = (
                        f"⚔️ {'Урон' if ru else 'Damage'}: <b>{dmg.total}</b> "
                        f"({dmg.detail})"
                    )
                    mechanics_lines.append(
                        f"{header}\n{roll_line}\n{hit_tag}\n{dmg_line}"
                    )
                    mechanics_lines.append(hp_line)
                else:
                    miss_tag = f"❌ <b>{'Промах!' if ru else 'Miss!'}</b>"
                    mechanics_lines.append(f"{header}\n{roll_line}\n{miss_tag}")
            except Exception:
                log.warning("NPC attack failed: %s", npc.damage_dice)

    for sc in decision.stat_changes:
        if sc.stat == "current_hp" and sc.delta < 0:
            hp_line = engine.apply_damage_verbose(char, abs(sc.delta), lang)
            mechanics_lines.append(hp_line)
        elif sc.stat == "current_hp" and sc.delta > 0:
            old_hp_val = char.current_hp
            engine.apply_healing(char, sc.delta)
            healed = char.current_hp - old_hp_val
            if healed > 0:
                mechanics_lines.append(f"💚 <b>+{healed} HP</b> → {char.current_hp}/{char.max_hp}")

    if decision.inventory_changes:
        changes = [
            {"name": ic.name, "quantity": ic.quantity, "action": ic.action,
             "description": ic.description}
            for ic in decision.inventory_changes
        ]
        for ic in decision.inventory_changes:
            prefix = "+" if ic.action != "remove" else "-"
            mechanics_lines.append(f"🎒 {prefix}{ic.quantity} {ic.name}" if ic.quantity != 1 else f"🎒 {prefix}{ic.name}")
        char.inventory = engine.merge_inventory(char.inventory, changes)
        char.inventory = engine.ensure_ammo(char.inventory)

    currency = gs.currency_name or ("зол." if lang == "ru" else "g")
    if decision.gold_change:
        char.gold = max(0, char.gold + decision.gold_change)
        sign = "+" if decision.gold_change > 0 else ""
        mechanics_lines.append(f"💰 <b>{sign}{decision.gold_change}</b> {currency}")

    # --- Smart XP fallback ---
    xp_to_grant = decision.xp_gained
    if xp_to_grant == 0 and had_checks:
        had_attack = bool(decision.attack_target_ac and decision.attack_target_ac > 0)
        had_saves = bool(decision.saving_throws)
        took_damage = any(npc.damage_dice for npc in decision.npc_actions) or any(
            sc.stat == "current_hp" and sc.delta < 0 for sc in decision.stat_changes
        )
        if took_damage:
            xp_to_grant = 75
        elif had_attack:
            xp_to_grant = 50
        elif had_saves:
            xp_to_grant = 50
        else:
            xp_to_grant = 25

    leveled_up = False
    old_hp = char.max_hp
    if xp_to_grant > 0:
        leveled_up = engine.grant_xp(char, xp_to_grant)
        mechanics_lines.append(f"✨ <b>+{xp_to_grant} XP</b>")

    if decision.location_change:
        _lo = player_action.lower()
        _MOVE_HINTS_RU = ("идти", "пойти", "бежать", "ползти", "лезть", "спуститься",
                          "подняться", "перейти", "войти", "выйти", "свернуть", "двигаться",
                          "отступить", "бежать", "убежать", "перебраться", "прыгнуть",
                          "к выходу", "в канал", "в коридор", "к двери", "в вентиляц",
                          "в канализац", "на склад", "в люк", "через люк", "к лестниц",
                          "в кабельн", "flee", "run", "go ", "move", "enter", "exit",
                          "climb", "jump", "crawl", "descend", "ascend", "head to")
        looks_like_move = any(h in _lo for h in _MOVE_HINTS_RU)
        forced_by_narrative = decision.on_failure and decision.location_change
        if looks_like_move or forced_by_narrative:
            gs.current_location = decision.location_change
            if decision.location_description:
                gs.location_description = decision.location_description
        else:
            log.warning("Blocked spurious location_change=%r on action=%r",
                        decision.location_change, player_action)
            decision.location_change = ""
            decision.location_description = ""
    if decision.quest_update:
        gs.current_quest = decision.quest_update
    if decision.is_combat_start:
        gs.in_combat = True
    if decision.is_combat_end:
        gs.in_combat = False

    # --- Build narrative from success/failure ---
    base_narrative = decision.narrative or "..."
    if any_succeeded and any_failed:
        extras = []
        if decision.on_success:
            extras.append(decision.on_success)
        if decision.on_failure:
            extras.append(decision.on_failure)
        if extras:
            base_narrative = f"{base_narrative}\n\n{' '.join(extras)}"
    elif any_failed and decision.on_failure:
        base_narrative = f"{base_narrative}\n\n{decision.on_failure}"
    elif any_succeeded and decision.on_success:
        base_narrative = f"{base_narrative}\n\n{decision.on_success}"

    narrative = md_to_html(base_narrative)
    gs.append_message("assistant", narrative)

    try:
        if decision.important_event:
            await save_episodic_memory(user.id, "event", decision.important_event, 7, db)
        await maybe_summarize(gs, user.content_tier.value)
        await maybe_run_deep_analysis(user, gs, db)
    except Exception:
        log.exception("Post-turn processing failed (non-fatal)")

    parts: list[str] = []
    if mechanics_lines:
        parts.append(f"<blockquote>{chr(10).join(mechanics_lines)}</blockquote>")
    parts.append(narrative)

    if decision.location_change and decision.location_description:
        loc_text = md_to_html(decision.location_description)
        parts.append(f"📍 <b>{decision.location_change}</b>\n<i>{loc_text}</i>")

    if decision.has_dialogue:
        hint = ("💬 <i>Напиши, что скажешь или сделаешь</i>"
                if lang == "ru"
                else "💬 <i>Type what you say or do</i>")
        parts.append(hint)
    else:
        hint = ("▶️ <i>Что делаешь?</i>"
                if lang == "ru"
                else "▶️ <i>What do you do?</i>")
        parts.append(hint)

    parts.append(f"<code>{compact_stat_bar(char, lang, currency)}</code>")

    if leveled_up:
        parts.append(t("LEVEL_UP", lang, name=char.name, level=str(char.level),
                        old_hp=str(old_hp), new_hp=str(char.max_hp)))
    if char.current_hp <= 0:
        parts.append(t("DYING", lang, name=char.name))

    elapsed = int((time.monotonic() - start_time) * 1000)
    log.info("Turn %d user %d: %dms", gs.turn_number, user.telegram_id, elapsed)

    # --- #20: Pick actions based on check outcome ---
    if had_checks:
        if any_failed and not any_succeeded and decision.on_failure_actions:
            final_actions = decision.on_failure_actions
            final_styles = decision.on_failure_styles
        elif any_succeeded and not any_failed and decision.on_success_actions:
            final_actions = decision.on_success_actions
            final_styles = decision.on_success_styles
        elif any_succeeded and any_failed:
            final_actions = decision.on_success_actions or decision.on_failure_actions or decision.available_actions
            final_styles = decision.on_success_styles or decision.on_failure_styles or decision.action_styles
        else:
            final_actions = decision.available_actions if decision.available_actions else None
            final_styles = decision.action_styles if decision.action_styles else None
    else:
        final_actions = decision.available_actions if decision.available_actions else None
        final_styles = decision.action_styles if decision.action_styles else None

    # --- #22: Save actions in session for menu restore ---
    gs.last_actions = final_actions or []
    gs.last_action_styles = final_styles or []

    if char.current_hp <= 0:
        kb = _death_save_keyboard(lang)
    else:
        combat_data = None
        if gs.in_combat:
            combat_data = {"inventory": char.inventory or [], "abilities": char.abilities or []}
        kb = actions_keyboard(final_actions, lang, styles=final_styles, combat_data=combat_data)

    full_text = truncate_for_telegram("\n\n".join(parts))

    sent = False
    if progress_msg:
        try:
            await progress_msg.edit_text(full_text, parse_mode="HTML", reply_markup=kb)
            sent = True
        except Exception:
            log.warning("Failed to edit progress message, sending new one")

    if not sent:
        try:
            await reply_target.answer(full_text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            log.exception("Failed to send turn response, trying without buttons")
            try:
                await reply_target.answer(full_text, parse_mode="HTML",
                                          reply_markup=actions_keyboard(None, lang))
            except Exception:
                log.exception("Failed to send even with default buttons")
                await reply_target.answer(full_text)
