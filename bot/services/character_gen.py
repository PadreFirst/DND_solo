"""Character generation — AI provides narrative, code handles all mechanics."""
from __future__ import annotations

import logging

from bot.models.character import Character
from bot.services.game_engine import (
    build_full_character,
    calculate_starting_hp,
    generate_starting_inventory,
    normalize_class_name,
    proficiency_bonus,
)
from bot.services.gemini import CharacterProposal, generate_structured
from bot.services.prompt_builder import character_creation_prompt

log = logging.getLogger(__name__)


async def generate_character(
    user_description: str,
    char_name: str,
    genre: str,
    tone: str,
    theme: str,
    language: str,
    content_tier: str,
) -> CharacterProposal:
    prompt = character_creation_prompt(
        user_description=user_description,
        char_name=char_name,
        genre=genre,
        tone=tone,
        theme=theme,
        language=language,
    )
    proposal: CharacterProposal = await generate_structured(
        prompt, CharacterProposal, content_tier=content_tier, heavy=True,
    )
    return proposal


def apply_proposal(char: Character, proposal: CharacterProposal, genre: str = "") -> None:
    """AI fills narrative fields; code computes all mechanics deterministically.

    Wrapped in a try/except so even if something goes wrong,
    we always produce a playable character with sensible defaults.
    """
    char.name = proposal.name or char.name or "Unnamed"

    try:
        build_full_character(
            char,
            char_class=proposal.char_class or "Fighter",
            race=proposal.race or "Human",
            backstory=proposal.backstory or "",
            proficient_skills=proposal.proficient_skills if isinstance(proposal.proficient_skills, list) else [],
            personality=proposal.personality_summary or "",
            genre=genre,
        )
    except Exception:
        log.exception("build_full_character failed, applying safe defaults")
        _apply_safe_defaults(char, proposal)


def _apply_safe_defaults(char: Character, proposal: CharacterProposal) -> None:
    """Fallback: create a basic but playable Fighter if anything goes wrong."""
    char.race = "Human"
    char.char_class = "Fighter"
    char.level = 1
    char.strength = 15
    char.dexterity = 13
    char.constitution = 14
    char.intelligence = 8
    char.wisdom = 12
    char.charisma = 10
    char.max_hp = 12
    char.current_hp = 12
    char.armor_class = 18
    char.proficiency_bonus = 2
    char.initiative_bonus = 1
    char.speed = 30
    char.gold = 15
    char.xp = 0
    char.proficient_skills = []
    char.saving_throw_proficiencies = ["strength", "constitution"]
    char.backstory = proposal.backstory or "A wandering adventurer seeking fortune."
    char.inventory = generate_starting_inventory("Fighter")
    char.hit_dice_current = 1
    char.hit_dice_max = 1
    char.hit_dice_face = "d10"
    char.spell_slots = {}
    char.death_save_successes = 0
    char.death_save_failures = 0
