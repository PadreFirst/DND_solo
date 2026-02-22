"""Main gameplay loop: single-pass — one Gemini call per turn."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
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
    format_character_sheet,
    format_inventory,
    format_quest,
    md_to_html,
    truncate_for_telegram,
)
from bot.utils.i18n import t
from bot.utils.keyboards import actions_keyboard, game_menu_keyboard, inventory_list_keyboard, rest_keyboard

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
    await message.answer(format_character_sheet(user.character), parse_mode="HTML")


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
        await cb.message.edit_reply_markup(
            reply_markup=actions_keyboard(None, user.language)
        )
        await cb.answer()
        return

    if action == "stats":
        char = await ensure_character(user, db)
        await cb.message.answer(format_character_sheet(char), parse_mode="HTML")
        await cb.answer()
        return

    if action == "inv":
        char = await ensure_character(user, db)
        text = format_inventory(char)
        kb = inventory_list_keyboard(char.inventory) if char.inventory else None
        await cb.message.answer(text, parse_mode="HTML", reply_markup=kb)
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
                prompt, content_tier=user.content_tier.value, system_instruction=sys_instr,
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
                prompt, content_tier=user.content_tier.value, system_instruction=sys_instr,
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


# ---- Inline button actions ----

@router.callback_query(F.data.startswith("act:"))
async def on_action_button(cb: CallbackQuery, db: AsyncSession) -> None:
    action_text = cb.data[4:]
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
    """Answer a meta-question without spending a game turn."""
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
            prompt, content_tier=user.content_tier.value, system_instruction=sys_instr,
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


# ---- Core game loop (single-pass) ----

_PROGRESS_STEPS_RU = [
    "🎲 <i>Обрабатываю ход...</i>",
    "🤔 <i>Думаю над ответом...</i>",
    "📝 <i>Пишу историю...</i>",
    "⚡ <i>Почти готово...</i>",
]
_PROGRESS_STEPS_EN = [
    "🎲 <i>Processing turn...</i>",
    "🤔 <i>Thinking...</i>",
    "📝 <i>Writing story...</i>",
    "⚡ <i>Almost there...</i>",
]


async def _keep_typing_with_progress(
    bot, chat_id: int, progress_msg: Message | None,
    stop_event: asyncio.Event, lang: str = "ru",
) -> None:
    steps = _PROGRESS_STEPS_RU if lang == "ru" else _PROGRESS_STEPS_EN
    step_idx = 0
    elapsed = 0.0
    interval = 3.5

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
            next_idx = min(int(elapsed / interval), len(steps) - 1)
            if next_idx != step_idx and progress_msg:
                step_idx = next_idx
                try:
                    await progress_msg.edit_text(steps[step_idx], parse_mode="HTML")
                except Exception:
                    pass


async def _process_player_action(
    reply_target: Message, telegram_id: int, username: str | None,
    player_action: str, db: AsyncSession,
) -> None:
    user = await get_or_create_user(telegram_id, username, db)
    if user.onboarding_state != OnboardingState.PLAYING:
        return
    char = await ensure_character(user, db)
    gs = await ensure_session(user, db)

    start_time = time.monotonic()
    track_interaction(user, player_action)
    track_action_choice(user, player_action)
    gs.append_message("user", player_action)
    gs.turn_number += 1

    sys_prompt = system_prompt(user.language, user.content_tier.value)
    context = await build_context(user, char, gs, db)

    # --- #8: Send placeholder immediately for perceived speed ---
    lang = user.language
    steps = _PROGRESS_STEPS_RU if lang == "ru" else _PROGRESS_STEPS_EN
    try:
        progress_msg = await reply_target.answer(steps[0], parse_mode="HTML")
    except Exception:
        progress_msg = None

    # Start typing + progressive status updates in background
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _keep_typing_with_progress(
            reply_target.bot, reply_target.chat.id, progress_msg, stop_typing, lang
        )
    )

    # --- Single Gemini call (system prompt separated for caching) ---
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
            mechanics_lines.append(atk.display_localized(lang))
            had_checks = True
            if atk.hit:
                any_succeeded = True
            else:
                any_failed = True
        except Exception:
            log.warning("Attack failed: ac=%s dice=%s", decision.attack_target_ac, decision.attack_damage_dice)

    # --- #1: Show NPC damage with HP result ---
    for npc in decision.npc_actions:
        if npc.damage_dice:
            try:
                dmg = engine.roll(npc.damage_dice, reason=f"{npc.name}")
                hp_line = engine.apply_damage_verbose(char, dmg.total, lang)
                mechanics_lines.append(f"{npc.name}: {dmg.display}")
                mechanics_lines.append(hp_line)
            except Exception:
                log.warning("NPC damage failed: %s", npc.damage_dice)

    # --- #1: Show stat_changes HP with result ---
    for sc in decision.stat_changes:
        if sc.stat == "current_hp" and sc.delta < 0:
            hp_line = engine.apply_damage_verbose(char, abs(sc.delta), lang)
            mechanics_lines.append(hp_line)
        elif sc.stat == "current_hp" and sc.delta > 0:
            old_hp_val = char.current_hp
            engine.apply_healing(char, sc.delta)
            healed = char.current_hp - old_hp_val
            if healed > 0:
                mechanics_lines.append(f"💚 +{healed} HP → {char.current_hp}/{char.max_hp}")

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

    if decision.gold_change:
        char.gold = max(0, char.gold + decision.gold_change)
        sign = "+" if decision.gold_change > 0 else ""
        mechanics_lines.append(f"💰 {sign}{decision.gold_change}g")

    # --- #5: Smart XP fallback ---
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
        mechanics_lines.append(f"✨ +{xp_to_grant} XP")

    if decision.location_change:
        gs.current_location = decision.location_change
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

    # --- #6: Compact stat bar ---
    parts.append(f"<code>{compact_stat_bar(char)}</code>")

    if leveled_up:
        parts.append(t("LEVEL_UP", lang, name=char.name, level=str(char.level),
                        old_hp=str(old_hp), new_hp=str(char.max_hp), prof=str(char.proficiency_bonus)))
    if char.current_hp <= 0:
        parts.append(t("DEATH", lang, name=char.name))

    elapsed = int((time.monotonic() - start_time) * 1000)
    log.info("Turn %d user %d: %dms", gs.turn_number, user.telegram_id, elapsed)

    # --- #7: Action buttons ---
    final_actions = decision.available_actions if decision.available_actions else None
    final_styles = decision.action_styles if decision.action_styles else None

    full_text = truncate_for_telegram("\n\n".join(parts))
    kb = actions_keyboard(final_actions, lang, styles=final_styles)

    # --- #8: Edit placeholder with final result ---
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
