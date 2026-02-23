"""Gemini integration via direct httpx calls through Cloudflare Worker proxy.

Bypasses google-genai client which doesn't properly support base_url for
geo-restricted regions. Uses the REST API directly.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

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


def _pick_model(heavy: bool = False, light: bool = False) -> str:
    if heavy and settings.gemini_model_heavy:
        return settings.gemini_model_heavy
    if light and settings.gemini_model_light:
        return settings.gemini_model_light
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
    system_instruction: str | None = None,
) -> dict:
    client = await _get_client()
    models_to_try = [model]
    if model != settings.gemini_model:
        models_to_try.append(settings.gemini_model)

    last_err = None
    for attempt_model in models_to_try:
        for attempt in range(3):
            url = f"{_BASE}/v1beta/models/{attempt_model}:generateContent?key={_API_KEY}"
            body: dict = {"contents": contents}
            if generation_config:
                body["generationConfig"] = generation_config
            if safety_settings:
                body["safetySettings"] = safety_settings
            if system_instruction:
                body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

            resp = await client.post(url, json=body)
            data = resp.json()

            if "error" not in data:
                if attempt_model != model:
                    log.info("Fallback to %s succeeded (original %s unavailable)", attempt_model, model)
                return data

            err = data["error"]
            code = err.get("code", 0)
            last_err = err

            if code in (503, 429):
                wait = 2 ** attempt + 1
                log.warning("Gemini %s returned %d, retry %d in %ds", attempt_model, code, attempt + 1, wait)
                await asyncio.sleep(wait)
                continue
            else:
                raise GeminiError("api", Exception(f"{code} {err.get('status')}. {err.get('message', '')}"))

        log.warning("All retries exhausted for %s, trying next model", attempt_model)

    raise GeminiError("api", Exception(
        f"{last_err.get('code')} {last_err.get('status')}. {last_err.get('message', '')}"
    ))


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
    skill: str = Field(default="Perception", description="Skill name")
    dc: int = Field(default=10, description="Difficulty class")
    advantage: bool = False
    disadvantage: bool = False


class SavingThrowRequest(BaseModel):
    ability: str = Field(default="dexterity", description="strength/dexterity/constitution/intelligence/wisdom/charisma")
    dc: int = Field(default=10, description="Difficulty class")
    advantage: bool = False
    disadvantage: bool = False


class ItemChange(BaseModel):
    action: str = Field(default="add", description="'add' or 'remove'")
    name: str = ""
    quantity: int = 1
    weight: float = 0.0
    description: str = ""


class StatChange(BaseModel):
    stat: str = Field(default="", description="Field name: current_hp, gold, etc.")
    delta: int = Field(default=0, description="Change amount (negative for decrease)")


class NPCAction(BaseModel):
    name: str = ""
    action: str = ""
    damage_dice: str | None = ""
    attack_bonus: int = Field(default=3, description="NPC attack roll modifier (1d20 + this vs player AC). Typical: +3 to +8.")


class GameResponse(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    narrative: str = Field(default="", description="Scene up to the moment of uncertainty. 80-150 words. HTML only.")
    on_success: str = Field(default="", description="2-3 sentences: what happens if the check SUCCEEDS.")
    on_failure: str = Field(default="", description="2-3 sentences: what happens if the check FAILS. Must have real consequences.")
    has_dialogue: bool = Field(default=False, description="True if an NPC is speaking and player can respond.")
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
    location_description: str = Field(default="", description="If location_change is set: 2-3 sentences describing the new place — size, exits, key objects, lighting, atmosphere. SEPARATE from narrative.")
    quest_update: str = ""
    attack_target_hp: int = Field(default=0, description="Current HP of attack target (if attacking)")
    attack_target_max_hp: int = Field(default=0, description="Max HP of attack target (if attacking)")
    available_actions: list[str] = Field(default_factory=list)
    action_styles: list[str] = Field(default_factory=list, description="Style per action: 'combat','dialogue','explore','safe'. Same order as available_actions.")
    on_success_actions: list[str] = Field(default_factory=list, description="3-4 actions if checks SUCCEED.")
    on_success_styles: list[str] = Field(default_factory=list, description="Styles for on_success_actions.")
    on_failure_actions: list[str] = Field(default_factory=list, description="3-4 actions if checks FAIL.")
    on_failure_styles: list[str] = Field(default_factory=list, description="Styles for on_failure_actions.")
    is_combat_start: bool = False
    is_combat_end: bool = False
    important_event: str = ""


MechanicsDecision = GameResponse


class InventoryItem(BaseModel):
    name: str = ""
    type: str = Field(default="misc", description="weapon, armor, ammo, consumable, misc")
    description: str = ""
    equipped: bool = False


class AbilityProposal(BaseModel):
    name: str = ""
    type: str = Field(default="active", description="'active' or 'passive'")
    recharge: str = Field(default="", description="'short rest','long rest','at will','per turn','spell slots', or empty")
    desc: str = Field(default="", description="1 sentence: what does this ability do")


class CharacterProposal(BaseModel):
    """AI fills narrative fields + suggests inventory. Stats, HP, AC computed in code."""
    name: str = ""
    race: str = Field(default="Human", description="Character race: Human, Elf, Dwarf, etc.")
    char_class: str = Field(default="Fighter", description="DnD class: Fighter, Wizard, Rogue, Cleric, etc.")
    proficient_skills: list[str] = Field(default_factory=list, description="2-4 skill proficiencies")
    backstory: str = Field(default="", description="2-3 paragraph backstory matching the world")
    personality_summary: str = Field(default="", description="Short personality description")
    suggested_inventory: list[InventoryItem] = Field(default_factory=list, description="8-12 setting-appropriate starting items")
    suggested_abilities: list[AbilityProposal] = Field(default_factory=list, description="3-5 setting-appropriate class abilities")


class MissionProposal(BaseModel):
    quest_title: str = ""
    quest_description: str = ""
    opening_scene: str = ""
    starting_location: str = ""
    starting_location_description: str = Field(default="", description="2-3 sentences: layout, exits, cover, interactive objects, atmosphere of the starting location")
    hook_mystery: str = ""
    first_npc_name: str = ""
    first_npc_role: str = ""
    first_npc_personality: str = ""
    opening_actions: list[str] = Field(default_factory=list)
    currency_name: str = Field(default="gold", description="World-appropriate currency name: 'imperial credits', 'gold coins', 'shadow rubles', etc.")
    starting_gold: int = Field(default=10, description="Starting money amount appropriate for the world scale: 10 for fantasy gold, 500 for sci-fi credits, 5000 for modern currency")


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
        if "User location is not supported" in s:
            return "⚠️ API недоступен из региона. Проверь GEMINI_PROXY." if ru else "⚠️ API geo-blocked. Check GEMINI_PROXY."
        if "429" in s or "RESOURCE_EXHAUSTED" in s:
            return "⚠️ Лимит запросов. Подожди минуту." if ru else "⚠️ Rate limited. Wait a minute."
        if "API key" in s or "401" in s or "leaked" in s.lower():
            return "⚠️ Неверный API-ключ." if ru else "⚠️ Invalid API key."
        if "503" in s or "UNAVAILABLE" in s:
            return "⚠️ Модель перегружена. Попробуй через минуту." if ru else "⚠️ Model overloaded. Try in a minute."
        if "validation error" in s.lower():
            return "⚠️ AI ответил неожиданно. Попробуй ещё раз." if ru else "⚠️ AI responded unexpectedly. Try again."
        return f"⚠️ Ошибка AI: {s[:120]}" if ru else f"⚠️ AI error: {s[:120]}"


def _make_example(schema: type[BaseModel]) -> str:
    """Generate a flat example JSON for the model — no schema nesting, just key: placeholder."""
    full = schema.model_json_schema()
    defs = full.get("$defs", {})
    props = full.get("properties", {})

    def _placeholder(prop: dict, key: str = "") -> Any:
        if "$ref" in prop:
            ref_name = prop["$ref"].split("/")[-1]
            ref_schema = defs.get(ref_name, {})
            return _obj_placeholder(ref_schema)
        t = prop.get("type", "string")
        if t == "string":
            desc = prop.get("description", "")
            return desc if desc else f"<{key or 'text'}>"
        if t == "integer":
            return 1
        if t == "number":
            return 0.5
        if t == "boolean":
            return False
        if t == "array":
            items = prop.get("items", {})
            return [_placeholder(items, key)]
        return f"<{key}>"

    def _obj_placeholder(schema_obj: dict) -> dict:
        obj_props = schema_obj.get("properties", {})
        return {k: _placeholder(v) for k, v in obj_props.items()}

    example = {}
    for key, prop in props.items():
        example[key] = _placeholder(prop, key)
    return json.dumps(example, indent=2, ensure_ascii=False)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that Gemini sometimes adds despite JSON mode."""
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _repair_json(text: str) -> str:
    """Best-effort repair of malformed JSON from Gemini.

    Handles: control chars inside strings, truncated output, trailing commas.
    """
    import re

    # Remove control characters except \n \r \t inside strings
    cleaned = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            cleaned.append(ch)
            escape = False
            continue
        if ch == '\\':
            cleaned.append(ch)
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            cleaned.append(ch)
            continue
        if in_string:
            if ch == '\n':
                cleaned.append('\\n')
                continue
            if ch == '\r':
                continue
            if ch == '\t':
                cleaned.append('\\t')
                continue
            if ord(ch) < 32:
                continue
        cleaned.append(ch)
    text = "".join(cleaned)

    # Fix trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # If JSON is truncated (no closing }), try to close it
    if text.count('{') > text.count('}'):
        open_braces = text.count('{') - text.count('}')
        # Find last complete key-value pair
        last_quote = text.rfind('"')
        if last_quote > 0:
            # Check if we're in the middle of a string value
            after = text[last_quote + 1:].strip()
            if not after or after == '':
                text = text[:last_quote + 1]
                text += '"' * 0  # already closed
            # Close any unclosed strings
            quote_count = text.count('"')
            if quote_count % 2 != 0:
                text += '"'
        text += '}' * open_braces

    return text


def _get_origin_type(field) -> str:
    """Extract the base type from a field annotation for safe matching."""
    import typing
    ann = field.annotation
    origin = getattr(ann, "__origin__", None)
    if origin is list:
        return "list"
    if ann is int:
        return "int"
    if ann is float:
        return "float"
    if ann is bool:
        return "bool"
    if ann is str:
        return "str"
    ann_str = str(ann)
    if ann_str.startswith("list[") or ann_str.startswith("typing.List["):
        return "list"
    return ann_str


def _coerce_types(raw: dict, schema: type[BaseModel]) -> dict:
    """Best-effort type coercion so Gemini's sloppy JSON doesn't fail validation."""
    hints = schema.model_fields
    for key, field in hints.items():
        if key not in raw or raw[key] is None:
            if key in raw and raw[key] is None:
                origin = _get_origin_type(field)
                if origin == "list":
                    raw[key] = []
                elif origin == "str":
                    raw[key] = ""
                elif origin == "int":
                    raw[key] = 0
                elif origin == "float":
                    raw[key] = 0.0
                elif origin == "bool":
                    raw[key] = False
            continue
        val = raw[key]
        origin = _get_origin_type(field)
        if origin == "list" and isinstance(val, str):
            val = val.strip()
            if val.startswith("["):
                try:
                    raw[key] = json.loads(val.replace("'", '"'))
                except (json.JSONDecodeError, ValueError):
                    raw[key] = [s.strip().strip("'\"") for s in val.strip("[]").split(",") if s.strip()]
            elif val:
                raw[key] = [s.strip() for s in val.split(",")]
            else:
                raw[key] = []
        elif origin == "int" and isinstance(val, str):
            try:
                raw[key] = int(float(val)) if val.replace(".", "").replace("-", "").isdigit() else 0
            except (ValueError, TypeError):
                raw[key] = 0
        elif origin == "int" and isinstance(val, float):
            raw[key] = int(val)
        elif origin == "float" and isinstance(val, str):
            try:
                raw[key] = float(val)
            except (ValueError, TypeError):
                raw[key] = 0.0
        elif origin == "bool" and isinstance(val, str):
            raw[key] = val.lower() in ("true", "1", "yes")
        elif origin == "str" and not isinstance(val, str):
            raw[key] = str(val) if val is not None else ""
    return raw


def _coerce_nested(raw: dict, schema: type[BaseModel]) -> dict:
    """Recursively fix None values inside nested list[BaseModel] fields."""
    import typing
    for key, field in schema.model_fields.items():
        if key not in raw:
            continue
        ann = field.annotation
        origin = getattr(ann, "__origin__", None)
        if origin is not list:
            continue
        args = getattr(ann, "__args__", ())
        if not args:
            continue
        inner = args[0]
        if not (isinstance(inner, type) and issubclass(inner, BaseModel)):
            continue
        items = raw[key]
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            if isinstance(item, dict):
                for fk, ff in inner.model_fields.items():
                    if fk in item and item[fk] is None:
                        default = ff.default
                        if default is not None:
                            item[fk] = default
                        else:
                            ftype = _get_origin_type(ff)
                            if ftype == "str":
                                item[fk] = ""
                            elif ftype == "int":
                                item[fk] = 0
                            elif ftype == "float":
                                item[fk] = 0.0
                            elif ftype == "bool":
                                item[fk] = False
                            elif ftype == "list":
                                item[fk] = []
    return raw


async def generate_structured(
    prompt: str,
    schema: type[BaseModel],
    content_tier: str = "full",
    heavy: bool = False,
    max_tokens: int = 8192,
    system_instruction: str | None = None,
) -> BaseModel:
    model = _pick_model(heavy)
    example = _make_example(schema)
    full_prompt = (
        f"{prompt}\n\n"
        f"OUTPUT FORMAT: Return a single flat JSON object with these exact keys. "
        f"Fill ALL values with real, meaningful content. Here is an EXAMPLE of the structure (replace placeholder values with real ones):\n"
        f"{example}\n\n"
        f"CRITICAL: Output ONLY the JSON object. No markdown, no explanation, no schema — just the data."
    )
    log.debug("Gemini structured [%s] (%s)", model, schema.__name__)
    last_error = None
    for attempt in range(2):
        try:
            data = await _call_gemini(
                model=model,
                contents=[{"parts": [{"text": full_prompt}]}],
                generation_config={
                    "responseMimeType": "application/json",
                    "temperature": 0.5 if attempt == 0 else 0.3,
                    "maxOutputTokens": max_tokens,
                },
                safety_settings=SAFETY_OFF,
                system_instruction=system_instruction,
            )
            text = _extract_text(data)
            log.debug("Gemini structured response (attempt %d): %s", attempt + 1, text[:500])
            text = _strip_code_fences(text)

            # Try direct parse first, then repair
            raw = None
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                log.warning("JSON parse failed (attempt %d), raw response (first 500 chars): %s",
                            attempt + 1, text[:500])
                repaired = _repair_json(text)
                try:
                    raw = json.loads(repaired)
                    log.info("JSON repair succeeded")
                except json.JSONDecodeError as je:
                    log.warning("JSON repair also failed: %s", je)
                    if attempt == 0:
                        last_error = je
                        log.info("Retrying with lower temperature...")
                        await asyncio.sleep(1)
                        continue
                    raise

            if raw is None:
                raise json.JSONDecodeError("Failed to parse", text[:100], 0)

            if "properties" in raw and isinstance(raw.get("properties"), dict):
                first_val = next(iter(raw["properties"].values()), {})
                if isinstance(first_val, dict) and "type" in first_val:
                    log.warning("Gemini returned schema instead of data, extracting defaults")
                    flat = {}
                    for k, v in raw["properties"].items():
                        flat[k] = v.get("default", v.get("type", ""))
                    raw = flat
            raw = _coerce_types(raw, schema)
            raw = _coerce_nested(raw, schema)
            return schema.model_validate(raw)
        except GeminiError:
            raise
        except Exception as e:
            if attempt == 0:
                last_error = e
                log.warning("Structured gen attempt 1 failed: %s, retrying...", e)
                await asyncio.sleep(1)
                continue
            log.exception("Gemini structured failed [%s] after %d attempts", model, attempt + 1)
            raise GeminiError(f"structured/{schema.__name__}", e) from e

    raise GeminiError(f"structured/{schema.__name__}", last_error or Exception("all attempts failed"))


async def generate_narrative(
    prompt: str, content_tier: str = "full", system_instruction: str | None = None,
    light: bool = False,
) -> str:
    model = _pick_model(light=light)
    log.debug("Gemini narrative [%s]", model)
    try:
        data = await _call_gemini(
            model=model,
            contents=[{"parts": [{"text": prompt}]}],
            generation_config={"temperature": 1.0, "maxOutputTokens": 2048},
            safety_settings=SAFETY_OFF,
            system_instruction=system_instruction,
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
    light: bool = False,
) -> str:
    try:
        data = await _call_gemini(
            model=_pick_model(light=light),
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
