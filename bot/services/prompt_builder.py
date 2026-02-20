"""Loads prompt templates and fills them with context."""
from __future__ import annotations

from pathlib import Path

from bot.templates.prompts.content_policies import POLICIES

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "prompts"

_cache: dict[str, str] = {}


def _load(name: str) -> str:
    if name not in _cache:
        path = TEMPLATES_DIR / name
        _cache[name] = path.read_text(encoding="utf-8")
    return _cache[name]


def system_prompt(language: str, content_tier: str) -> str:
    tpl = _load("system.txt")
    return tpl.format(
        content_policy=POLICIES.get(content_tier, POLICIES["family"]),
        language=language,
    )


def character_creation_prompt(
    user_description: str,
    char_name: str,
    genre: str,
    tone: str,
    theme: str,
    language: str,
) -> str:
    tpl = _load("character_creation.txt")
    return tpl.format(
        user_description=user_description,
        char_name=char_name,
        genre=genre,
        tone=tone,
        theme=theme,
        language=language,
    )


def mission_prompt(
    char_name: str,
    race: str,
    char_class: str,
    backstory: str,
    genre: str,
    tone: str,
    theme: str,
    language: str,
) -> str:
    tpl = _load("mission.txt")
    return tpl.format(
        char_name=char_name,
        race=race,
        char_class=char_class,
        backstory=backstory,
        genre=genre,
        tone=tone,
        theme=theme,
        language=language,
    )


def pass1_prompt(context: str, player_action: str, language: str = "en") -> str:
    tpl = _load("pass1_mechanics.txt")
    return tpl.format(context=context, player_action=player_action, language=language)


def pass2_prompt(
    context: str,
    player_action: str,
    mechanics_results: str,
    language: str,
) -> str:
    tpl = _load("pass2_narrative.txt")
    return tpl.format(
        context=context,
        player_action=player_action,
        mechanics_results=mechanics_results,
        language=language,
    )


def personalization_prompt(
    interactions: str,
    current_weights: str,
) -> str:
    tpl = _load("personalization.txt")
    return tpl.format(
        interactions=interactions,
        current_weights=current_weights,
    )
