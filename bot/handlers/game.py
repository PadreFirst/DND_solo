"""Main gameplay loop: player action -> Pass 1 (mechanics) -> engine -> Pass 2 (narrative)."""
from __future__ import annotations

import json
import logging
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import OnboardingState
from bot.services import game_engine as engine
from bot.services.gemini import MechanicsDecision, generate_narrative, generate_structured
from bot.services.memory import build_context, maybe_summarize, save_episodic_memory
from bot.services.personalization import maybe_run_deep_analysis, track_action_choice, track_interaction
from bot.services.prompt_builder import pass1_prompt, pass2_prompt, system_prompt
from bot.services.user_service import ensure_character, ensure_session, get_or_create_user
from bot.utils.formatters import (
    format_character_sheet,
    format_dice_roll,
    format_inventory,
    format_quest,
    truncate_for_telegram,
)
from bot.utils.keyboards import actions_keyboard

log = logging.getLogger(__name__)
router = Router(name="game")


# ---- Slash commands during gameplay ----

@router.message(Command("stats"))
async def cmd_stats(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if user.onboarding_state != OnboardingState.PLAYING or not user.character:
        await message.answer("Start a game first with /start")
        return
    await message.answer(format_character_sheet(user.character), parse_mode="HTML")


@router.message(Command("quest"))
async def cmd_quest(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if user.onboarding_state != OnboardingState.PLAYING:
        return
    gs = await ensure_session(user, db)
    await message.answer(
        format_quest(gs.current_quest, gs.current_location),
        parse_mode="HTML",
    )


@router.message(Command("debug"))
async def cmd_debug(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if not user.character:
        await message.answer("No active game.")
        return
    gs = await ensure_session(user, db)
    debug_info = {
        "user_id": user.telegram_id,
        "onboarding": user.onboarding_state.value,
        "content_tier": user.content_tier.value,
        "language": user.language,
        "character": user.character.to_sheet_dict(),
        "session": gs.to_state_dict(),
        "msg_count": gs.message_count,
        "prefs": {
            "combat": user.combat_pref,
            "puzzle": user.puzzle_pref,
            "dialogue": user.dialogue_pref,
            "exploration": user.exploration_pref,
            "romance": user.romance_tolerance,
            "gore": user.gore_tolerance,
            "humor": user.humor_pref,
            "engagement": user.engagement_level,
        },
    }
    text = f"<pre>{json.dumps(debug_info, indent=2, ensure_ascii=False)[:3800]}</pre>"
    await message.answer(text, parse_mode="HTML")


# ---- Inline button actions ----

@router.callback_query(F.data.startswith("act:"))
async def on_action_button(cb: CallbackQuery, db: AsyncSession) -> None:
    action_text = cb.data[4:]
    await cb.answer()
    await _process_player_action(cb.message, cb.from_user.id, cb.from_user.username, action_text, db)


# ---- Free text: dispatches to onboarding or gameplay ----

@router.message(F.text)
async def on_game_text(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)

    if user.onboarding_state != OnboardingState.PLAYING:
        from bot.handlers.start import handle_onboarding_text
        handled = await handle_onboarding_text(message, user, db)
        if handled:
            return
        return

    await _process_player_action(message, message.from_user.id, message.from_user.username,
                                  message.text.strip(), db)


# ---- Core game loop ----

async def _process_player_action(
    reply_target: Message,
    telegram_id: int,
    username: str | None,
    player_action: str,
    db: AsyncSession,
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

    # --- Build context ---
    sys_prompt = system_prompt(user.language, user.content_tier.value)
    context = await build_context(user, char, gs, db)
    full_context = f"{sys_prompt}\n\n{context}"

    # --- Pass 1: Mechanics decision ---
    try:
        p1_prompt = pass1_prompt(full_context, player_action)
        decision: MechanicsDecision = await generate_structured(
            p1_prompt, MechanicsDecision, content_tier=user.content_tier.value
        )
    except Exception:
        log.exception("Pass 1 failed")
        await reply_target.answer("⚠️ The game master is thinking... try again.",
                                   parse_mode="HTML")
        return

    # --- Execute mechanics ---
    mechanics_lines: list[str] = []

    for sc in decision.skill_checks:
        result = engine.skill_check(
            char, sc.skill, sc.dc, advantage=sc.advantage, disadvantage=sc.disadvantage
        )
        mechanics_lines.append(result.display)

    for st in decision.saving_throws:
        result = engine.saving_throw(
            char, st.ability, st.dc, advantage=st.advantage, disadvantage=st.disadvantage
        )
        mechanics_lines.append(result.display)

    if decision.attack_target_ac and decision.attack_target_ac > 0:
        atk_result = engine.make_attack(
            char,
            target_ac=decision.attack_target_ac,
            damage_dice=decision.attack_damage_dice or "1d8",
            ability=decision.attack_ability,
            proficient=True,
        )
        mechanics_lines.append(atk_result.display)
        if atk_result.hit and atk_result.damage_roll:
            mechanics_lines.append(
                f"You deal {atk_result.damage_roll.total} damage to the enemy!"
            )

    for npc_act in decision.npc_actions:
        if npc_act.damage_dice:
            npc_dmg = engine.roll(npc_act.damage_dice, reason=f"{npc_act.name} damage")
            status = engine.apply_damage(char, npc_dmg.total)
            mechanics_lines.append(
                f"{npc_act.name} attacks! Damage: {npc_dmg.display} | You: {status}"
            )

    for sc in decision.stat_changes:
        field = sc.stat
        if field == "current_hp" and sc.delta < 0:
            engine.apply_damage(char, abs(sc.delta))
            mechanics_lines.append(f"You take {abs(sc.delta)} damage! HP: {char.current_hp}/{char.max_hp}")
        elif field == "current_hp" and sc.delta > 0:
            engine.apply_healing(char, sc.delta)
            mechanics_lines.append(f"Healed {sc.delta} HP! HP: {char.current_hp}/{char.max_hp}")

    for ic in decision.inventory_changes:
        if ic.action == "add":
            inv = char.inventory
            inv.append({"name": ic.name, "quantity": ic.quantity,
                        "weight": ic.weight, "description": ic.description})
            char.inventory = inv
            mechanics_lines.append(f"🎒 Obtained: {ic.name}" + (f" x{ic.quantity}" if ic.quantity > 1 else ""))
        elif ic.action == "remove":
            inv = char.inventory
            inv = [item for item in inv if item.get("name", "").lower() != ic.name.lower()]
            char.inventory = inv
            mechanics_lines.append(f"🎒 Lost: {ic.name}")

    if decision.gold_change:
        char.gold = max(0, char.gold + decision.gold_change)
        sign = "+" if decision.gold_change > 0 else ""
        mechanics_lines.append(f"💰 Gold: {sign}{decision.gold_change} (total: {char.gold})")

    leveled_up = False
    old_hp = char.max_hp
    if decision.xp_gained > 0:
        leveled_up = engine.grant_xp(char, decision.xp_gained)
        mechanics_lines.append(f"✨ +{decision.xp_gained} XP")

    if decision.location_change:
        gs.current_location = decision.location_change
        mechanics_lines.append(f"📍 Moved to: {decision.location_change}")

    if decision.quest_update:
        gs.current_quest = decision.quest_update

    if decision.is_combat_start:
        gs.in_combat = True
    if decision.is_combat_end:
        gs.in_combat = False

    mechanics_text = "\n".join(mechanics_lines) if mechanics_lines else "No mechanical effects."

    # --- Pass 2: Narrative ---
    try:
        p2_prompt = pass2_prompt(full_context, player_action, mechanics_text, user.language)
        narrative = await generate_narrative(p2_prompt, content_tier=user.content_tier.value)
    except Exception:
        log.exception("Pass 2 failed")
        narrative = decision.narration_context or "The story continues..."

    gs.append_message("assistant", narrative)

    # --- Save episodic memory if important ---
    if decision.important_event:
        await save_episodic_memory(
            user.id, "event", decision.important_event, importance=7, db=db
        )

    # --- Summarize if needed ---
    await maybe_summarize(gs, user.content_tier.value)

    # --- Personalization analysis ---
    await maybe_run_deep_analysis(user, gs, db)

    # --- Build response message ---
    response_parts: list[str] = []

    if mechanics_lines:
        dice_block = "\n".join(mechanics_lines)
        response_parts.append(f"<blockquote>{dice_block}</blockquote>")

    response_parts.append(narrative)

    if leveled_up:
        from bot.utils.i18n import t
        response_parts.append(t("LEVEL_UP", user.language,
                                 name=char.name, level=str(char.level),
                                 old_hp=str(old_hp), new_hp=str(char.max_hp),
                                 prof=str(char.proficiency_bonus)))

    if char.current_hp <= 0:
        from bot.utils.i18n import t
        response_parts.append(t("DEATH", user.language, name=char.name))

    full_response = "\n\n".join(response_parts)
    full_response = truncate_for_telegram(full_response)

    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    log.info("Turn %d for user %d completed in %dms", gs.turn_number, user.telegram_id, elapsed_ms)

    await reply_target.answer(
        full_response,
        parse_mode="HTML",
        reply_markup=actions_keyboard(decision.available_actions),
    )
