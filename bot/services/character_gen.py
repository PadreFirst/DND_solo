"""Character generation — AI provides narrative, code handles all mechanics."""
from __future__ import annotations

import logging

from bot.models.character import Character
from bot.services.game_engine import build_full_character, normalize_class_name
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


def apply_proposal(char: Character, proposal: CharacterProposal) -> None:
    """AI fills narrative fields; code computes all mechanics deterministically."""
    char.name = proposal.name or char.name or "Unnamed"

    build_full_character(
        char,
        char_class=proposal.char_class or "Fighter",
        race=proposal.race or "Human",
        backstory=proposal.backstory,
        proficient_skills=proposal.proficient_skills,
        personality=proposal.personality_summary,
    )
