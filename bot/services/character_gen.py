"""Character generation — bridges Gemini proposals to Character model."""
from __future__ import annotations

import logging

from bot.models.character import Character
from bot.services.game_engine import calculate_starting_hp, proficiency_bonus
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
        prompt, CharacterProposal, content_tier=content_tier,
    )
    return proposal


def apply_proposal(char: Character, proposal: CharacterProposal) -> None:
    char.name = proposal.name
    char.race = proposal.race
    char.char_class = proposal.char_class
    char.level = 1

    char.strength = _clamp_stat(proposal.strength)
    char.dexterity = _clamp_stat(proposal.dexterity)
    char.constitution = _clamp_stat(proposal.constitution)
    char.intelligence = _clamp_stat(proposal.intelligence)
    char.wisdom = _clamp_stat(proposal.wisdom)
    char.charisma = _clamp_stat(proposal.charisma)

    starting_hp = calculate_starting_hp(char.char_class, char.con_mod)
    char.max_hp = max(1, starting_hp)
    char.current_hp = char.max_hp

    char.proficiency_bonus = proficiency_bonus(1)
    char.proficient_skills = proposal.proficient_skills
    char.saving_throw_proficiencies = proposal.saving_throws
    char.backstory = proposal.backstory

    char.armor_class = 10 + char.dex_mod
    char.initiative_bonus = char.dex_mod
    char.speed = 30

    inv = [
        {"name": item.name, "quantity": item.quantity,
         "weight": item.weight, "description": item.description}
        for item in proposal.starting_inventory
    ]
    char.inventory = inv
    char.gold = max(0, proposal.starting_gold)
    char.xp = 0


def _clamp_stat(val: int) -> int:
    return max(3, min(20, val))
