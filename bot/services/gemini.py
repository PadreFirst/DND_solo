"""Two-pass Gemini integration.

Pass 1: structured JSON — decides WHAT mechanics apply.
Pass 2: narrative text  — describes WHAT happened, beautifully.

Uses prompt-based JSON extraction (like the working Boss bot) instead of
response_schema which is geo-restricted in some regions.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from bot.config import settings

log = logging.getLogger(__name__)

_LLM_TIMEOUT = 90

_http_options_kwargs: dict[str, Any] = {}
if settings.gemini_proxy:
    import httpx
    log.info("Gemini using proxy: %s", settings.gemini_proxy[:30] + "...")
    _http_options_kwargs = {
        "http_options": types.HttpOptions(
            client_args={"transport": httpx.HTTPTransport(proxy=settings.gemini_proxy)},
            async_client_args={"transport": httpx.AsyncHTTPTransport(proxy=settings.gemini_proxy)},
        )
    }

client = genai.Client(api_key=settings.gemini_api_key, **_http_options_kwargs)


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


def _pick_model(heavy: bool = False) -> str:
    if heavy and settings.gemini_model_heavy:
        return settings.gemini_model_heavy
    return settings.gemini_model


def _schema_to_prompt_hint(schema: type[BaseModel]) -> str:
    """Generate a JSON schema description for the prompt instead of using response_schema."""
    schema_json = schema.model_json_schema()

    def _simplify(s: dict) -> dict:
        out: dict[str, Any] = {}
        props = s.get("properties", {})
        defs = s.get("$defs", {})
        for name, prop in props.items():
            ref = prop.get("$ref")
            if ref:
                ref_name = ref.split("/")[-1]
                out[name] = _simplify(defs.get(ref_name, {}))
                continue
            items = prop.get("items", {})
            if items and items.get("$ref"):
                ref_name = items["$ref"].split("/")[-1]
                out[name] = [_simplify(defs.get(ref_name, {}))]
                continue
            t = prop.get("type", "string")
            default = prop.get("default")
            desc = prop.get("description", "")
            hint = t
            if desc:
                hint = f"{t} — {desc}"
            if default is not None and default != "" and default != []:
                hint += f" (default: {default})"
            out[name] = hint
        return out

    simplified = _simplify(schema_json)
    return json.dumps(simplified, indent=2, ensure_ascii=False)


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
            return f"⚠️ Модель не найдена. Проверь GEMINI_MODEL в .env."
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
            return f"⚠️ Model not found. Check GEMINI_MODEL in .env."
        return f"⚠️ AI error: {s[:200]}"

    def user_message(self, lang: str) -> str:
        return self.user_message_ru if lang == "ru" else self.user_message_en


async def generate_structured(
    prompt: str,
    schema: type[BaseModel],
    content_tier: str = "full",
    heavy: bool = False,
) -> BaseModel:
    """Generate structured JSON using prompt-based schema (no response_schema, works globally)."""
    model = _pick_model(heavy)
    schema_hint = _schema_to_prompt_hint(schema)
    full_prompt = (
        f"{prompt}\n\n"
        f"RESPOND WITH ONLY VALID JSON matching this exact structure:\n"
        f"{schema_hint}\n\n"
        f"Output ONLY the JSON object, no markdown, no explanation."
    )
    log.debug("Gemini structured [%s] (%s):\n%s", model, schema.__name__, full_prompt[:500])
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.8,
                    max_output_tokens=4096,
                ),
            ),
            timeout=_LLM_TIMEOUT,
        )
        text = response.text
        log.debug("Gemini structured response:\n%s", text[:1000])
        data = json.loads(text)
        return schema.model_validate(data)
    except asyncio.TimeoutError as e:
        log.error("Gemini structured timeout after %ss", _LLM_TIMEOUT)
        raise GeminiError(f"structured/{schema.__name__}", e) from e
    except json.JSONDecodeError as e:
        log.error("Gemini returned invalid JSON: %s", e)
        raise GeminiError(f"structured/{schema.__name__}", e) from e
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
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=1.0,
                    max_output_tokens=2048,
                ),
            ),
            timeout=_LLM_TIMEOUT,
        )
        text = response.text
        log.debug("Gemini narrative response:\n%s", text[:1000])
        return text
    except asyncio.TimeoutError as e:
        log.error("Gemini narrative timeout")
        raise GeminiError("narrative", e) from e
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
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=_pick_model(heavy=False),
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            ),
            timeout=_LLM_TIMEOUT,
        )
        return response.text
    except asyncio.TimeoutError as e:
        log.error("Gemini text timeout")
        raise GeminiError("text", e) from e
    except Exception as e:
        log.exception("Gemini text generation failed")
        raise GeminiError("text", e) from e
