"""Onboarding: /start -> language -> age -> setting -> character -> mission."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import AgeGroup, ContentTier, OnboardingState, User
from bot.services.character_gen import apply_proposal, generate_character
from bot.services.gemini import MissionProposal, generate_structured
from bot.services.prompt_builder import mission_prompt
from bot.services.user_service import ensure_character, ensure_session, get_or_create_user, reset_game
from bot.utils.formatters import format_character_sheet, truncate_for_telegram
from bot.utils.i18n import t
from bot.utils.keyboards import (
    actions_keyboard,
    age_keyboard,
    char_creation_method_keyboard,
    character_review_keyboard,
    genre_keyboard,
    language_keyboard,
    theme_keyboard,
    tone_keyboard,
)

log = logging.getLogger(__name__)
router = Router(name="onboarding")

AGE_MAP = {
    "13-15": AgeGroup.TEEN,
    "16-17": AgeGroup.YOUNG,
    "18-24": AgeGroup.ADULT_YOUNG,
    "25-34": AgeGroup.ADULT,
    "35+": AgeGroup.MATURE,
}


# ---- /start ----

@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if user.onboarding_state == OnboardingState.PLAYING:
        await reset_game(user, db)

    user.onboarding_state = OnboardingState.LANG_ASKED
    await message.answer(t("WELCOME", "en"), parse_mode="HTML",
                         reply_markup=language_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    await message.answer(t("MENU_HELP", user.language), parse_mode="HTML")


# ---- Language (FIRST step) ----

@router.callback_query(F.data.startswith("lang:"))
async def on_lang(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    user.language = cb.data.split(":")[1]
    user.onboarding_state = OnboardingState.AGE_ASKED
    await cb.message.edit_text(
        t("AGE_SELECT", user.language), parse_mode="HTML",
        reply_markup=age_keyboard(user.language),
    )
    await cb.answer()


# ---- Age ----

@router.callback_query(F.data.startswith("age:"))
async def on_age(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    age_key = cb.data.split(":")[1]
    age_group = AGE_MAP.get(age_key, AgeGroup.ADULT)
    user.apply_age_defaults(age_group)

    user.onboarding_state = OnboardingState.SETTING_GENRE
    await cb.message.edit_text(
        t("GENRE_SELECT", user.language), parse_mode="HTML",
        reply_markup=genre_keyboard(user.language),
    )
    await cb.answer()


# ---- Genre ----

@router.callback_query(F.data.startswith("genre:"))
async def on_genre(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    gs = await ensure_session(user, db)
    choice = cb.data.split(":")[1]

    if choice == "custom":
        user.onboarding_state = OnboardingState.SETTING_GENRE_CUSTOM
        await cb.message.edit_text(t("GENRE_CUSTOM", user.language), parse_mode="HTML")
    else:
        gs.genre = choice
        user.onboarding_state = OnboardingState.SETTING_TONE
        await cb.message.edit_text(
            t("TONE_SELECT", user.language), parse_mode="HTML",
            reply_markup=tone_keyboard(user.language),
        )
    await cb.answer()


# ---- Tone ----

@router.callback_query(F.data.startswith("tone:"))
async def on_tone(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    gs = await ensure_session(user, db)
    choice = cb.data.split(":")[1]

    if choice == "custom":
        user.onboarding_state = OnboardingState.SETTING_TONE_CUSTOM
        await cb.message.edit_text(t("TONE_CUSTOM", user.language), parse_mode="HTML")
    else:
        gs.tone = choice
        user.onboarding_state = OnboardingState.SETTING_THEME
        await cb.message.edit_text(
            t("THEME_SELECT", user.language), parse_mode="HTML",
            reply_markup=theme_keyboard(user.language),
        )
    await cb.answer()


# ---- Theme ----

@router.callback_query(F.data.startswith("theme:"))
async def on_theme(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    gs = await ensure_session(user, db)
    choice = cb.data.split(":")[1]

    if choice == "custom":
        user.onboarding_state = OnboardingState.SETTING_THEME_CUSTOM
        await cb.message.edit_text(t("THEME_CUSTOM", user.language), parse_mode="HTML")
    else:
        gs.theme = choice
        user.onboarding_state = OnboardingState.CHAR_NAME
        await cb.message.edit_text(t("CHAR_NAME_ASK", user.language), parse_mode="HTML")
    await cb.answer()


# ---- Character creation method ----

@router.callback_query(F.data.startswith("charmethod:"))
async def on_char_method(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    method = cb.data.split(":")[1]

    if method == "free":
        user.onboarding_state = OnboardingState.CHAR_FREE_DESC
        await cb.message.edit_text(t("CHAR_FREE_DESC", user.language), parse_mode="HTML")
    else:
        user.onboarding_state = OnboardingState.CHAR_Q1_RACE
        await cb.message.edit_text(t("CHAR_Q1", user.language), parse_mode="HTML")
    await cb.answer()


# ---- Character review ----

@router.callback_query(F.data.startswith("charreview:"))
async def on_char_review(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    choice = cb.data.split(":")[1]

    if choice == "regen":
        user.onboarding_state = OnboardingState.CHAR_FREE_DESC
        await cb.message.edit_text(t("CHAR_FREE_DESC", user.language), parse_mode="HTML")
        await cb.answer()
        return

    char = await ensure_character(user, db)
    gs = await ensure_session(user, db)
    user.onboarding_state = OnboardingState.MISSION_INTRO

    await cb.message.edit_text(t("MISSION_GENERATING", user.language), parse_mode="HTML")
    await cb.answer()

    try:
        prompt = mission_prompt(
            char_name=char.name, race=char.race, char_class=char.char_class,
            backstory=char.backstory, genre=gs.genre, tone=gs.tone,
            theme=gs.theme, language=user.language,
        )
        mission: MissionProposal = await generate_structured(
            prompt, MissionProposal, content_tier=user.content_tier.value
        )

        gs.current_quest = f"{mission.quest_title}: {mission.quest_description}"
        gs.current_location = mission.starting_location
        if mission.first_npc_name:
            gs.active_npcs = [{"name": mission.first_npc_name,
                               "role": mission.first_npc_role,
                               "personality": mission.first_npc_personality}]
        gs.turn_number = 1
        gs.append_message("assistant", mission.opening_scene)
        user.onboarding_state = OnboardingState.PLAYING

        opening = mission.opening_scene
        actions = _localized_default_actions(user.language)

        await cb.message.answer(
            t("GAME_START", user.language, opening_scene=truncate_for_telegram(opening, 3500)),
            parse_mode="HTML",
            reply_markup=actions_keyboard(actions),
        )
    except Exception:
        log.exception("Mission generation failed")
        await cb.message.answer(t("ERROR", user.language), parse_mode="HTML")


# ---- Text input during onboarding (called from game.py) ----

async def handle_onboarding_text(message: Message, user: User, db: AsyncSession) -> bool:
    """Handle text input during onboarding. Returns True if handled."""
    text = message.text.strip()
    state = user.onboarding_state

    if state == OnboardingState.SETTING_GENRE_CUSTOM:
        gs = await ensure_session(user, db)
        gs.genre = text[:100]
        user.onboarding_state = OnboardingState.SETTING_TONE
        await message.answer(t("TONE_SELECT", user.language), parse_mode="HTML",
                             reply_markup=tone_keyboard(user.language))
        return True

    if state == OnboardingState.SETTING_TONE_CUSTOM:
        gs = await ensure_session(user, db)
        gs.tone = text[:100]
        user.onboarding_state = OnboardingState.SETTING_THEME
        await message.answer(t("THEME_SELECT", user.language), parse_mode="HTML",
                             reply_markup=theme_keyboard(user.language))
        return True

    if state == OnboardingState.SETTING_THEME_CUSTOM:
        gs = await ensure_session(user, db)
        gs.theme = text[:100]
        user.onboarding_state = OnboardingState.CHAR_NAME
        await message.answer(t("CHAR_NAME_ASK", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_NAME:
        char = await ensure_character(user, db)
        char.name = text[:100]
        user.onboarding_state = OnboardingState.CHAR_METHOD
        await message.answer(
            t("CHAR_METHOD", user.language, name=char.name),
            parse_mode="HTML",
            reply_markup=char_creation_method_keyboard(user.language),
        )
        return True

    if state == OnboardingState.CHAR_FREE_DESC:
        await _generate_char(message, user, text, db)
        return True

    # Sequential questions
    if state == OnboardingState.CHAR_Q1_RACE:
        gs = await ensure_session(user, db)
        gs.world_state = _update_char_answers(gs.world_state, "race", text)
        user.onboarding_state = OnboardingState.CHAR_Q2_CLASS
        await message.answer(t("CHAR_Q2", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_Q2_CLASS:
        gs = await ensure_session(user, db)
        gs.world_state = _update_char_answers(gs.world_state, "class", text)
        user.onboarding_state = OnboardingState.CHAR_Q3_PERSONALITY
        await message.answer(t("CHAR_Q3", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_Q3_PERSONALITY:
        gs = await ensure_session(user, db)
        gs.world_state = _update_char_answers(gs.world_state, "personality", text)
        user.onboarding_state = OnboardingState.CHAR_Q4_MOTIVATION
        await message.answer(t("CHAR_Q4", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_Q4_MOTIVATION:
        gs = await ensure_session(user, db)
        gs.world_state = _update_char_answers(gs.world_state, "motivation", text)
        user.onboarding_state = OnboardingState.CHAR_Q5_QUIRK
        await message.answer(t("CHAR_Q5", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_Q5_QUIRK:
        gs = await ensure_session(user, db)
        gs.world_state = _update_char_answers(gs.world_state, "quirk", text)
        user.onboarding_state = OnboardingState.CHAR_EXTRA
        await message.answer(t("CHAR_EXTRA", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_EXTRA:
        gs = await ensure_session(user, db)
        import json
        answers = json.loads(gs.world_state) if gs.world_state and gs.world_state != "{}" else {}

        skip_words = {"нет", "no", "готово", "done", "нет спасибо", "skip", "-", "ок", "ok"}
        extra = "" if text.lower().strip() in skip_words else f" Additional details: {text}"

        desc = (
            f"Race: {answers.get('race', 'Human')}. "
            f"Class: {answers.get('class', 'Fighter')}. "
            f"Personality: {answers.get('personality', '')}. "
            f"Motivation: {answers.get('motivation', '')}. "
            f"Unusual trait: {answers.get('quirk', '')}."
            f"{extra}"
        )
        gs.world_state = "{}"
        await _generate_char(message, user, desc, db)
        return True

    return False


def _update_char_answers(world_state: str, key: str, value: str) -> str:
    import json
    data = json.loads(world_state) if world_state and world_state != "{}" else {}
    data[key] = value
    return json.dumps(data, ensure_ascii=False)


async def _generate_char(message: Message, user: User, description: str, db: AsyncSession) -> None:
    char = await ensure_character(user, db)
    gs = await ensure_session(user, db)

    user.onboarding_state = OnboardingState.CHAR_GENERATING
    await message.answer(t("CHAR_GENERATING", user.language), parse_mode="HTML")

    try:
        proposal = await generate_character(
            user_description=description, char_name=char.name,
            genre=gs.genre, tone=gs.tone, theme=gs.theme,
            language=user.language, content_tier=user.content_tier.value,
        )
        apply_proposal(char, proposal)
        user.onboarding_state = OnboardingState.CHAR_REVIEW

        sheet_text = format_character_sheet(char)
        await message.answer(
            t("CHAR_REVIEW", user.language, sheet=sheet_text, backstory=char.backstory),
            parse_mode="HTML",
            reply_markup=character_review_keyboard(user.language),
        )
    except Exception:
        log.exception("Character generation failed")
        user.onboarding_state = OnboardingState.CHAR_FREE_DESC
        await message.answer(t("ERROR", user.language), parse_mode="HTML")


def _localized_default_actions(lang: str) -> list[str]:
    if lang == "ru":
        return ["Осмотреться", "Поговорить", "Исследовать", "Проверить инвентарь", "Идти вперёд"]
    return ["Look around", "Talk to someone", "Explore", "Check inventory", "Move forward"]
