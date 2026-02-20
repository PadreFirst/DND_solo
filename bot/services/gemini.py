"""Gemini integration via direct httpx calls through Cloudflare Worker proxy.

Bypasses google-genai client which doesn't properly support base_url for
geo-restricted regions. Uses the REST API directly.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
from pydantic import BaseModel, Field

from bot.config import settings

log = logging.getLogger(__name__)

_LLM_TIMEOUT = 90

_BASE = settings.gemini_proxy.rstrip("/") if settings.gemini_proxy else "https://generativelanguage.googleapis.com"
_API_KEY = settings.gemini_api_key

_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_LLM_TIMEOUT)
    return _client


def _pick_model(heavy: bool = False) -> str:
    if heavy and settings.gemini_model_heavy:
        return settings.gemini_model_heavy
    return settings.gemini_model


SAFETY_OFF = [
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
]


async def _call_gemini(
    model: str,
    contents: list[dict],
    generation_config: dict | None = None,
    safety_settings: list[dict] | None = None,
) -> dict:
    url = f"{_BASE}/v1beta/models/{model}:generateContent?key={_API_KEY}"
    body: dict = {"contents": contents}
    if generation_config:
        body["generationConfig"] = generation_config
    if safety_settings:
        body["safetySettings"] = safety_settings

    client = await _get_client()
    resp = await client.post(url, json=body)
    data = resp.json()

    if "error" in data:
        err = data["error"]
        raise GeminiError("api", Exception(f"{err.get('code')} {err.get('status')}. {err.get('message', '')}"))

    return data


def _extract_text(data: dict) -> str:
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise GeminiError("parse", Exception(f"No text in response: {json.dumps(data)[:200]}"))


# --- Pydantic schemas ---

class InventoryItem(BaseModel):
    name: str = ""
    quantity: int = 1
    weight: float = 0.0
    description: str = ""


class SkillCheckRequest(BaseModel):
    skill: str = Field(description="Skill name")
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
    narration_context: str = ""
    skill_checks: list[SkillCheckRequest] = Field(default_factory=list)
    saving_throws: list[SavingThrowRequest] = Field(default_factory=list)
    attack_target_ac: int = 0
    attack_damage_dice: str = ""
    attack_ability: str = "strength"
    npc_actions: list[NPCAction] = Field(default_factory=list)
    stat_changes: list[StatChange] = Field(default_factory=list)
    inventory_changes: list[ItemChange] = Field(default_factory=list)
    xp_gained: int = 0
    gold_change: int = 0
    location_change: str = ""
    quest_update: str = ""
    available_actions: list[str] = Field(default_factory=lambda: ["Look around", "Talk", "Attack", "Use item"])
    is_combat_start: bool = False
    is_combat_end: bool = False
    important_event: str = ""


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


class GeminiError(Exception):
    def __init__(self, operation: str, original: Exception):
        self.operation = operation
        self.original = original
        super().__init__(f"Gemini [{operation}]: {original}")

    def user_message(self, lang: str) -> str:
        s = str(self.original)
        ru = lang == "ru"
        if "location" in s:
            return "⚠️ API недоступен из региона. Проверь GEMINI_PROXY." if ru else "⚠️ API geo-blocked. Check GEMINI_PROXY."
        if "429" in s or "RESOURCE_EXHAUSTED" in s:
            return "⚠️ Лимит запросов. Подожди минуту." if ru else "⚠️ Rate limited. Wait a minute."
        if "API key" in s or "401" in s:
            return "⚠️ Неверный API-ключ." if ru else "⚠️ Invalid API key."
        return f"⚠️ Ошибка AI: {s[:150]}" if ru else f"⚠️ AI error: {s[:150]}"


def _schema_hint(schema: type[BaseModel]) -> str:
    s = schema.model_json_schema()
    props = s.get("properties", {})
    out = {}
    for k, v in props.items():
        t = v.get("type", "string")
        d = v.get("default")
        out[k] = f"{t}" + (f" (default: {d})" if d is not None and d != "" and d != [] else "")
    return json.dumps(out, indent=2, ensure_ascii=False)


async def generate_structured(
    prompt: str,
    schema: type[BaseModel],
    content_tier: str = "full",
    heavy: bool = False,
) -> BaseModel:
    model = _pick_model(heavy)
    hint = _schema_hint(schema)
    full_prompt = (
        f"{prompt}\n\n"
        f"RESPOND WITH ONLY VALID JSON matching this structure:\n{hint}\n"
        f"Output ONLY the JSON object."
    )
    log.debug("Gemini structured [%s] (%s)", model, schema.__name__)
    try:
        data = await _call_gemini(
            model=model,
            contents=[{"parts": [{"text": full_prompt}]}],
            generation_config={
                "responseMimeType": "application/json",
                "temperature": 0.8,
                "maxOutputTokens": 4096,
            },
            safety_settings=SAFETY_OFF,
        )
        text = _extract_text(data)
        log.debug("Gemini structured response: %s", text[:500])
        return schema.model_validate(json.loads(text))
    except GeminiError:
        raise
    except Exception as e:
        log.exception("Gemini structured failed [%s]", model)
        raise GeminiError(f"structured/{schema.__name__}", e) from e


async def generate_narrative(prompt: str, content_tier: str = "full") -> str:
    model = _pick_model(heavy=False)
    log.debug("Gemini narrative [%s]", model)
    try:
        data = await _call_gemini(
            model=model,
            contents=[{"parts": [{"text": prompt}]}],
            generation_config={"temperature": 1.0, "maxOutputTokens": 2048},
            safety_settings=SAFETY_OFF,
        )
        return _extract_text(data)
    except GeminiError:
        raise
    except Exception as e:
        log.exception("Gemini narrative failed")
        raise GeminiError("narrative", e) from e


async def generate_text(
    prompt: str,
    content_tier: str = "full",
    temperature: float = 0.9,
    max_tokens: int = 4096,
) -> str:
    try:
        data = await _call_gemini(
            model=_pick_model(heavy=False),
            contents=[{"parts": [{"text": prompt}]}],
            generation_config={"temperature": temperature, "maxOutputTokens": max_tokens},
            safety_settings=SAFETY_OFF,
        )
        return _extract_text(data)
    except GeminiError:
        raise
    except Exception as e:
        log.exception("Gemini text failed")
        raise GeminiError("text", e) from e
