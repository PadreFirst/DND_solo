"""Two-pass Gemini integration.

Pass 1: structured JSON — decides WHAT mechanics apply.
Pass 2: narrative text  — describes WHAT happened, beautifully.

Supports proxy for geo-restricted regions and separate heavy model for creation tasks.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from bot.config import settings

log = logging.getLogger(__name__)


def _build_client() -> genai.Client:
    kwargs: dict[str, Any] = {"api_key": settings.gemini_api_key}

    if settings.gemini_proxy:
        proxy = settings.gemini_proxy
        log.info("Gemini using proxy: %s", proxy[:30] + "...")
        kwargs["http_options"] = types.HttpOptions(
            client_args={
                "transport": httpx.HTTPTransport(proxy=proxy),
            },
            async_client_args={
                "transport": httpx.AsyncHTTPTransport(proxy=proxy),
            },
        )

    return genai.Client(**kwargs)


client = _build_client()

SAFETY_OFF = [
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="OFF"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"),
]

SAFETY_MODERATE = [
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_MEDIUM_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_MEDIUM_AND_ABOVE"),
]


# --- Pydantic schemas for structured output ---

class InventoryItem(BaseModel):
    name: str = ""
    quantity: int = 1
    weight: float = 0.0
    description: str = ""


class DiceRequest(BaseModel):
    dice: str = Field(description="Dice notation, e.g. '1d20', '2d6'")
    modifier_ability: str = Field(default="", description="Ability to use as modifier")
    proficient: bool = False
    advantage: bool = False
    disadvantage: bool = False
    reason: str = ""


class SkillCheckRequest(BaseModel):
    skill: str = Field(description="Skill name, e.g. 'Perception', 'Stealth'")
    dc: int = Field(description="Difficulty class")
    advantage: bool = False
    disadvantage: bool = False


class SavingThrowRequest(BaseModel):
    ability: str = Field(description="strength/dexterity/constitution/intelligence/wisdom/charisma")
    dc: int = Field(description="Difficulty class")
    advantage: bool = False
    disadvantage: bool = False


class ItemChange(BaseModel):
    action: str = Field(description="'add' or 'remove'")
    name: str = ""
    quantity: int = 1
    weight: float = 0.0
    description: str = ""


class StatChange(BaseModel):
    stat: str = Field(description="Field name: current_hp, gold, etc.")
    delta: int = Field(description="Change amount (negative for decrease)")


class NPCAction(BaseModel):
    name: str = ""
    action: str = ""
    damage_dice: str = ""


class MechanicsDecision(BaseModel):
    narration_context: str = Field(default="", description="Brief context for the narrator")
    skill_checks: list[SkillCheckRequest] = Field(default_factory=list)
    saving_throws: list[SavingThrowRequest] = Field(default_factory=list)
    attack_target_ac: int = Field(default=0, description="Target AC if player attacks, 0 if no attack")
    attack_damage_dice: str = Field(default="", description="Damage dice, e.g. '1d8'")
    attack_ability: str = Field(default="strength")
    npc_actions: list[NPCAction] = Field(default_factory=list)
    stat_changes: list[StatChange] = Field(default_factory=list)
    inventory_changes: list[ItemChange] = Field(default_factory=list)
    xp_gained: int = 0
    gold_change: int = 0
    location_change: str = Field(default="")
    quest_update: str = Field(default="")
    available_actions: list[str] = Field(default_factory=lambda: ["Look around", "Talk", "Attack", "Use item"])
    is_combat_start: bool = False
    is_combat_end: bool = False
    important_event: str = Field(default="")


class CharacterProposal(BaseModel):
    name: str = ""
    race: str = ""
    char_class: str = ""
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
    proficient_skills: list[str] = Field(default_factory=list)
    saving_throws: list[str] = Field(default_factory=list)
    backstory: str = ""
    starting_inventory: list[InventoryItem] = Field(default_factory=list)
    starting_gold: int = 0
    personality_summary: str = ""


class MissionProposal(BaseModel):
    quest_title: str = ""
    quest_description: str = ""
    opening_scene: str = ""
    starting_location: str = ""
    hook_mystery: str = ""
    first_npc_name: str = ""
    first_npc_role: str = ""
    first_npc_personality: str = ""


class PersonalizationAnalysis(BaseModel):
    combat_pref: float = Field(default=0.5, ge=0, le=1)
    puzzle_pref: float = Field(default=0.5, ge=0, le=1)
    dialogue_pref: float = Field(default=0.5, ge=0, le=1)
    exploration_pref: float = Field(default=0.5, ge=0, le=1)
    romance_tolerance: float = Field(default=0.3, ge=0, le=1)
    gore_tolerance: float = Field(default=0.3, ge=0, le=1)
    humor_pref: float = Field(default=0.5, ge=0, le=1)
    engagement_level: float = Field(default=0.5, ge=0, le=1)
    reasoning: str = ""


def _get_safety(content_tier: str) -> list[types.SafetySetting]:
    if content_tier == "full":
        return SAFETY_OFF
    return SAFETY_MODERATE


def _pick_model(heavy: bool = False) -> str:
    if heavy and settings.gemini_model_heavy:
        return settings.gemini_model_heavy
    return settings.gemini_model


class GeminiError(Exception):
    """Wraps Gemini API errors with user-friendly context."""

    def __init__(self, operation: str, original: Exception):
        self.operation = operation
        self.original = original
        super().__init__(f"Gemini [{operation}]: {original}")

    @property
    def user_message_ru(self) -> str:
        s = str(self.original)
        if "location is not supported" in s:
            return "⚠️ API недоступен из этого региона. Нужна прокси (GEMINI_PROXY в .env)."
        if "RESOURCE_EXHAUSTED" in s or "429" in s:
            return "⚠️ Лимит запросов. Подожди минуту и попробуй снова."
        if "API key" in s or "401" in s:
            return "⚠️ Неверный API-ключ Gemini."
        if "not found" in s.lower() or "404" in s:
            return f"⚠️ Модель {_pick_model()} не найдена. Проверь GEMINI_MODEL в .env."
        return f"⚠️ Ошибка AI: {s[:200]}"

    @property
    def user_message_en(self) -> str:
        s = str(self.original)
        if "location is not supported" in s:
            return "⚠️ API not available from this region. Set GEMINI_PROXY in .env."
        if "RESOURCE_EXHAUSTED" in s or "429" in s:
            return "⚠️ Rate limited. Wait a minute and try again."
        if "API key" in s or "401" in s:
            return "⚠️ Invalid Gemini API key."
        if "not found" in s.lower() or "404" in s:
            return f"⚠️ Model {_pick_model()} not found. Check GEMINI_MODEL in .env."
        return f"⚠️ AI error: {s[:200]}"

    def user_message(self, lang: str) -> str:
        return self.user_message_ru if lang == "ru" else self.user_message_en


async def generate_structured(
    prompt: str,
    schema: type[BaseModel],
    content_tier: str = "full",
    heavy: bool = False,
) -> BaseModel:
    model = _pick_model(heavy)
    log.debug("Gemini structured [%s] (%s):\n%s", model, schema.__name__, prompt[:500])
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                safety_settings=_get_safety(content_tier),
                temperature=0.8,
            ),
        )
        text = response.text
        log.debug("Gemini structured response:\n%s", text[:1000])
        data = json.loads(text)
        return schema.model_validate(data)
    except Exception as e:
        log.exception("Gemini structured generation failed [%s]", model)
        raise GeminiError(f"structured/{schema.__name__}", e) from e


async def generate_narrative(
    prompt: str,
    content_tier: str = "full",
) -> str:
    model = _pick_model(heavy=False)
    log.debug("Gemini narrative [%s]:\n%s", model, prompt[:500])
    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=_get_safety(content_tier),
                temperature=1.0,
                max_output_tokens=2048,
            ),
        )
        text = response.text
        log.debug("Gemini narrative response:\n%s", text[:1000])
        return text
    except Exception as e:
        log.exception("Gemini narrative generation failed")
        raise GeminiError("narrative", e) from e


async def generate_text(
    prompt: str,
    content_tier: str = "full",
    temperature: float = 0.9,
    max_tokens: int = 4096,
) -> str:
    try:
        response = await client.aio.models.generate_content(
            model=_pick_model(heavy=False),
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=_get_safety(content_tier),
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text
    except Exception as e:
        log.exception("Gemini text generation failed")
        raise GeminiError("text", e) from e
