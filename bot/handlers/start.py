"""Onboarding: /start -> language -> age -> world -> tone -> character -> mission."""
from __future__ import annotations

import json
import logging
import random

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import AgeGroup, OnboardingState, User
from bot.services.character_gen import apply_proposal, generate_character
from bot.services.gemini import GeminiError, MissionProposal, generate_structured
from bot.services.prompt_builder import mission_prompt
from bot.services.user_service import ensure_character, ensure_session, get_or_create_user, reset_game
from bot.utils.formatters import format_character_sheet, md_to_html, truncate_for_telegram
from bot.utils.i18n import t
from bot.utils.keyboards import (
    TONE_DESCRIPTIONS,
    actions_keyboard,
    age_keyboard,
    char_creation_method_keyboard,
    character_review_keyboard,
    language_keyboard,
    tone_keyboard,
    world_keyboard,
)

log = logging.getLogger(__name__)
router = Router(name="onboarding")

AGE_MAP = {
    "13-15": AgeGroup.TEEN, "16-17": AgeGroup.YOUNG,
    "18-24": AgeGroup.ADULT_YOUNG, "25-34": AgeGroup.ADULT, "35+": AgeGroup.MATURE,
}

WORLD_PRESETS = {
    "star_wars": (
        "Star Wars universe — the Galactic Empire, Rebel Alliance, Jedi and Sith, "
        "lightsabers, the Force (Light and Dark sides), blasters, starships, droids, "
        "cantinas, bounty hunters. Planets: Coruscant, Tatooine, Hoth, Dagobah, etc. "
        "Races: humans, Twi'leks, Wookiees, Rodians, Zabrak, Togruta. "
        "Currency: Imperial credits. Technology: hyperdrives, holoprojectors, bacta tanks."
    ),
    "lotr": (
        "Middle-earth (Lord of the Rings / Tolkien) — Elves, Dwarves, Hobbits, Men, Orcs, "
        "Wizards (Istari). Locations: the Shire, Rivendell, Moria, Rohan, Gondor, Mordor. "
        "Artifacts: Rings of Power, palantíri, mithril. Magic is rare and subtle. "
        "Themes: corruption of power, fellowship, long journeys through dangerous wilds. "
        "Currency: silver pennies, gold coins of Gondor."
    ),
    "harry_potter": (
        "Wizarding World (Harry Potter) — Hogwarts School of Witchcraft and Wizardry, "
        "Ministry of Magic, Diagon Alley, Hogsmeade, Forbidden Forest, Azkaban. "
        "Magic: wands, spells (Expelliarmus, Lumos, Patronus), potions, magical creatures "
        "(hippogriffs, thestrals, house-elves). Houses: Gryffindor, Slytherin, Ravenclaw, Hufflepuff. "
        "Currency: Galleons, Sickles, Knuts. Dark forces: Death Eaters, dark wizards, Unforgivable Curses."
    ),
    "witcher": (
        "The Witcher universe (Andrzej Sapkowski) — the Continent, a dark medieval world "
        "where humans, elves, dwarves coexist uneasily. Witchers are mutated monster hunters. "
        "Magic: Signs (Igni, Aard, Quen, Yrden, Axii), sorceresses, chaos magic. "
        "Monsters: drowners, griffins, vampires, leshens, djinn. Politics: Nilfgaard vs Northern Kingdoms. "
        "Currency: crowns, orens. Themes: moral ambiguity, racism, the lesser evil."
    ),
    "marvel": (
        "Marvel Universe — superheroes and supervillains, enhanced individuals, mutants, "
        "alien invasions, cosmic entities. Organizations: Avengers, S.H.I.E.L.D., HYDRA, X-Men. "
        "Tech: Stark Industries, vibranium, Pym particles. Locations: New York, Wakanda, Asgard, "
        "the Quantum Realm. Powers: mutations, serums, tech suits, magic (sorcerers, Infinity Stones). "
        "Currency: US dollars. Themes: responsibility, identity, protecting the world."
    ),
    "got": (
        "Westeros & Essos (Game of Thrones / A Song of Ice and Fire) — medieval political intrigue, "
        "noble houses vying for the Iron Throne. The Seven Kingdoms, the Wall, the Free Cities. "
        "Houses: Stark, Lannister, Targaryen, Baratheon, Greyjoy, Tyrell, Martell. "
        "Magic is rare: dragons, White Walkers, faceless men, red priests, wargs, greenseers. "
        "Currency: gold dragons, silver stags. Themes: power, betrayal, survival, war."
    ),
    "classic_fantasy": "Classic high fantasy — dragons, kingdoms, ancient magic, epic quests",
    "dark_fantasy": "Dark fantasy — morally gray world, gritty violence, cursed lands, eldritch horrors",
    "scifi": "Sci-fi — space travel, alien species, advanced technology, interstellar politics",
    "pirate": "Pirate adventure — island nations, sea monsters, treasure hunts, naval combat",
    "noir": "Noir detective — crime-ridden cities, mysteries, conspiracies, morally complex characters",
    "horror": "Horror — psychological terror, supernatural threats, survival, dread atmosphere",
    "steampunk": "Steampunk — Victorian era, steam-powered machines, airships, clockwork automatons",
    "postapoc": "Post-apocalyptic — ruined civilization, mutants, scavenging, faction warfare",
}


async def _typing(event: Message | CallbackQuery) -> None:
    chat_id = event.chat.id if isinstance(event, Message) else event.message.chat.id
    bot = event.bot if isinstance(event, Message) else event.message.bot
    await bot.send_chat_action(chat_id, ChatAction.TYPING)


async def _send_error(event: Message | CallbackQuery, user: User, error: Exception) -> None:
    if isinstance(error, GeminiError):
        text = error.user_message(user.language)
    else:
        text = t("ERROR", user.language)
    text += "\n\n" + (_retry_hint_ru if user.language == "ru" else _retry_hint_en)
    target = event if isinstance(event, Message) else event.message
    await target.answer(text, parse_mode="HTML")

_retry_hint_ru = "<i>Прогресс сохранён. Просто повтори последнее действие или отправь любое сообщение.</i>"
_retry_hint_en = "<i>Progress saved. Just repeat your last action or send any message.</i>"


# ---- /start ----

@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    if user.onboarding_state == OnboardingState.PLAYING:
        await reset_game(user, db)
    user.onboarding_state = OnboardingState.LANG_ASKED
    await message.answer(t("WELCOME", "en"), parse_mode="HTML", reply_markup=language_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message, db: AsyncSession) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, db)
    await message.answer(t("MENU_HELP", user.language), parse_mode="HTML")


# ---- 1. Language ----

@router.callback_query(F.data.startswith("lang:"))
async def on_lang(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    user.language = cb.data.split(":")[1]
    user.onboarding_state = OnboardingState.AGE_ASKED
    await cb.message.edit_text(t("ONBOARDING_PLAN", user.language), parse_mode="HTML")
    await cb.message.answer(t("AGE_SELECT", user.language), parse_mode="HTML",
                            reply_markup=age_keyboard(user.language))
    await cb.answer()


# ---- 2. Age ----

@router.callback_query(F.data.startswith("age:"))
async def on_age(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    age_group = AGE_MAP.get(cb.data.split(":")[1], AgeGroup.ADULT)
    user.apply_age_defaults(age_group)
    user.onboarding_state = OnboardingState.WORLD_SETUP
    await cb.message.edit_text(t("WORLD_SELECT", user.language), parse_mode="HTML",
                               reply_markup=world_keyboard(user.language))
    await cb.answer()


# ---- 3. World ----

@router.callback_query(F.data.startswith("world:"))
async def on_world(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    gs = await ensure_session(user, db)
    choice = cb.data.split(":")[1]

    if choice == "custom":
        user.onboarding_state = OnboardingState.WORLD_CUSTOM
        await cb.message.edit_text(t("WORLD_CUSTOM", user.language), parse_mode="HTML")
    else:
        gs.genre = choice
        gs.world_state = json.dumps({"world_desc": WORLD_PRESETS.get(choice, choice)})
        user.onboarding_state = OnboardingState.TONE_SELECT
        await cb.message.edit_text(t("TONE_SELECT", user.language), parse_mode="HTML",
                                   reply_markup=tone_keyboard(user.language))
    await cb.answer()


# ---- 4. Tone ----

@router.callback_query(F.data.startswith("tone:"))
async def on_tone(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    gs = await ensure_session(user, db)
    tone_key = cb.data.split(":")[1]
    gs.tone = TONE_DESCRIPTIONS.get(tone_key, tone_key)
    user.onboarding_state = OnboardingState.CHAR_NAME
    await cb.message.edit_text(t("CHAR_NAME_ASK", user.language), parse_mode="HTML")
    await cb.answer()


# ---- 5. Character method ----

@router.callback_query(F.data.startswith("charmethod:"))
async def on_char_method(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)
    if cb.data.split(":")[1] == "free":
        user.onboarding_state = OnboardingState.CHAR_FREE_DESC
        await cb.message.edit_text(t("CHAR_FREE_DESC", user.language), parse_mode="HTML")
    else:
        user.onboarding_state = OnboardingState.CHAR_Q1_RACE
        await cb.message.edit_text(t("CHAR_Q1", user.language), parse_mode="HTML")
    await cb.answer()


# ---- 6. Character review ----

@router.callback_query(F.data.startswith("charreview:"))
async def on_char_review(cb: CallbackQuery, db: AsyncSession) -> None:
    user = await get_or_create_user(cb.from_user.id, cb.from_user.username, db)

    if cb.data.split(":")[1] == "regen":
        user.onboarding_state = OnboardingState.CHAR_FREE_DESC
        await cb.message.edit_text(t("CHAR_FREE_DESC", user.language), parse_mode="HTML")
        await cb.answer()
        return

    await _typing(cb)
    char = await ensure_character(user, db)
    gs = await ensure_session(user, db)
    user.onboarding_state = OnboardingState.MISSION_INTRO
    wait = random.randint(40, 75)
    await cb.message.edit_text(t("MISSION_GENERATING", user.language, wait=str(wait)), parse_mode="HTML")
    await cb.answer()

    try:
        world_data = json.loads(gs.world_state) if gs.world_state and gs.world_state != "{}" else {}
        world_desc = world_data.get("world_desc", gs.genre)

        prompt = mission_prompt(
            char_name=char.name, race=char.race, char_class=char.char_class,
            backstory=char.backstory, genre=world_desc, tone=gs.tone,
            theme="adventure", language=user.language,
        )
        mission: MissionProposal = await generate_structured(
            prompt, MissionProposal, content_tier=user.content_tier.value, heavy=True,
        )

        gs.current_quest = f"{mission.quest_title}: {mission.quest_description}"
        gs.current_location = mission.starting_location
        if mission.currency_name:
            gs.currency_name = mission.currency_name
        if mission.starting_gold and mission.starting_gold > 0:
            char.gold = mission.starting_gold
        if mission.first_npc_name:
            gs.active_npcs = [{"name": mission.first_npc_name,
                               "role": mission.first_npc_role,
                               "personality": mission.first_npc_personality}]
        gs.turn_number = 1

        opening = md_to_html(mission.opening_scene) if mission.opening_scene else ""
        if not opening.strip():
            opening = (
                f"<b>{mission.quest_title}</b>\n\n"
                f"{md_to_html(mission.quest_description)}\n\n"
                f"📍 <i>{mission.starting_location}</i>"
            )
        gs.append_message("assistant", opening)
        user.onboarding_state = OnboardingState.PLAYING

        actions = mission.opening_actions if mission.opening_actions else _default_actions(user.language)
        await cb.message.answer(
            t("GAME_START", user.language, opening_scene=truncate_for_telegram(opening, 3500)),
            parse_mode="HTML",
            reply_markup=actions_keyboard(actions, user.language, styles=None),
        )
    except Exception as e:
        log.exception("Mission generation failed")
        user.onboarding_state = OnboardingState.CHAR_REVIEW
        sheet = format_character_sheet(char, user.language)
        backstory_html = md_to_html(char.backstory) if char.backstory else ""
        await cb.message.answer(
            t("CHAR_REVIEW", user.language, sheet=sheet, backstory=backstory_html),
            parse_mode="HTML",
            reply_markup=character_review_keyboard(user.language),
        )
        await _send_error(cb, user, e)


# ---- Text input during onboarding (called from game.py) ----

async def handle_onboarding_text(message: Message, user: User, db: AsyncSession) -> bool:
    text = message.text.strip()
    state = user.onboarding_state

    if state == OnboardingState.WORLD_CUSTOM:
        await _typing(message)
        gs = await ensure_session(user, db)
        gs.genre = "custom"
        gs.world_state = json.dumps({"world_desc": text}, ensure_ascii=False)
        user.onboarding_state = OnboardingState.TONE_SELECT
        await message.answer(t("TONE_SELECT", user.language), parse_mode="HTML",
                             reply_markup=tone_keyboard(user.language))
        return True

    if state == OnboardingState.CHAR_NAME:
        char = await ensure_character(user, db)
        char.name = text[:100]
        user.onboarding_state = OnboardingState.CHAR_METHOD
        await message.answer(
            t("CHAR_METHOD", user.language, name=char.name), parse_mode="HTML",
            reply_markup=char_creation_method_keyboard(user.language),
        )
        return True

    if state == OnboardingState.CHAR_FREE_DESC:
        await _typing(message)
        await _generate_char(message, user, text, db)
        return True

    if state == OnboardingState.CHAR_Q1_RACE:
        gs = await ensure_session(user, db)
        gs.world_state = _upsert_answers(gs.world_state, "race", text)
        user.onboarding_state = OnboardingState.CHAR_Q2_CLASS
        await message.answer(t("CHAR_Q2", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_Q2_CLASS:
        gs = await ensure_session(user, db)
        gs.world_state = _upsert_answers(gs.world_state, "class", text)
        user.onboarding_state = OnboardingState.CHAR_Q3_PERSONALITY
        await message.answer(t("CHAR_Q3", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_Q3_PERSONALITY:
        gs = await ensure_session(user, db)
        gs.world_state = _upsert_answers(gs.world_state, "personality", text)
        user.onboarding_state = OnboardingState.CHAR_Q4_MOTIVATION
        await message.answer(t("CHAR_Q4", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_Q4_MOTIVATION:
        gs = await ensure_session(user, db)
        gs.world_state = _upsert_answers(gs.world_state, "motivation", text)
        user.onboarding_state = OnboardingState.CHAR_Q5_QUIRK
        await message.answer(t("CHAR_Q5", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_Q5_QUIRK:
        gs = await ensure_session(user, db)
        gs.world_state = _upsert_answers(gs.world_state, "quirk", text)
        user.onboarding_state = OnboardingState.CHAR_EXTRA
        await message.answer(t("CHAR_EXTRA", user.language), parse_mode="HTML")
        return True

    if state == OnboardingState.CHAR_EXTRA:
        await _typing(message)
        gs = await ensure_session(user, db)
        answers = json.loads(gs.world_state) if gs.world_state else {}
        skip_words = {"нет", "no", "готово", "done", "skip", "-", "ок", "ok", "нет спасибо"}
        extra = "" if text.lower().strip() in skip_words else f" Additional: {text}"
        desc = (
            f"Race: {answers.get('race', '')}. "
            f"Class: {answers.get('class', '')}. "
            f"Personality: {answers.get('personality', '')}. "
            f"Motivation: {answers.get('motivation', '')}. "
            f"Unusual trait: {answers.get('quirk', '')}.{extra}"
        )
        await _generate_char(message, user, desc, db)
        return True

    return False


def _upsert_answers(world_state: str, key: str, value: str) -> str:
    data = json.loads(world_state) if world_state and world_state != "{}" else {}
    data[key] = value
    return json.dumps(data, ensure_ascii=False)


async def _generate_char(message: Message, user: User, description: str, db: AsyncSession) -> None:
    char = await ensure_character(user, db)
    gs = await ensure_session(user, db)
    prev_state = user.onboarding_state
    user.onboarding_state = OnboardingState.CHAR_GENERATING
    wait = random.randint(40, 75)
    await message.answer(t("CHAR_GENERATING", user.language, wait=str(wait)), parse_mode="HTML")

    try:
        world_data = json.loads(gs.world_state) if gs.world_state and gs.world_state != "{}" else {}
        world_desc = world_data.get("world_desc", gs.genre or "fantasy")

        proposal = await generate_character(
            user_description=description, char_name=char.name,
            genre=world_desc, tone=gs.tone or "adaptive",
            theme="adventure",
            language=user.language, content_tier=user.content_tier.value,
        )
        apply_proposal(char, proposal, genre=world_desc)
        user.onboarding_state = OnboardingState.CHAR_REVIEW

        sheet = format_character_sheet(char, user.language)
        backstory = md_to_html(char.backstory) if char.backstory else (
            "<i>Тайна, скрытая даже от самого героя...</i>" if user.language == "ru"
            else "<i>A mystery, hidden even from the hero themselves...</i>"
        )
        await message.answer(
            t("CHAR_REVIEW", user.language, sheet=sheet, backstory=backstory),
            parse_mode="HTML",
            reply_markup=character_review_keyboard(user.language),
        )
    except Exception as e:
        log.exception("Character generation failed")
        user.onboarding_state = prev_state
        await _send_error(message, user, e)


def _default_actions(lang: str) -> list[str]:
    if lang == "ru":
        return ["Осмотреться", "Поговорить", "Исследовать", "Проверить инвентарь"]
    return ["Look around", "Talk to someone", "Explore", "Check inventory"]
