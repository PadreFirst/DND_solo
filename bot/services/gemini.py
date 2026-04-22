from __future__ import annotations

import asyncio
import json
import logging

import httpx

from bot.config import ROOT_DIR, settings
from bot.schemas import TurnPlan

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (ROOT_DIR / "system_prompt.md").read_text(encoding="utf-8")

_FORMAT_HINT = (
    "Верни ТОЛЬКО JSON с полями TurnPlan:\n"
    "{\n"
    '  "narrative": "...",\n'
    '  "gm_question_mode": false,\n'
    '  "gm_answer": "",\n'
    '  "rolls": [{"type":"skill|attack|save","label":"...","ability":"STR|DEX|CON|INT|WIS|CHA","dc":12,"advantage":false,"disadvantage":false}],\n'
    '  "enemy_actions": [{"name":"...","attack_bonus":4,"damage_dice":"1d6","reason":"..."}],\n'
    '  "direct_hp_change": 0,\n'
    '  "inventory_changes": [{"action":"add|remove|use","name":"...","quantity":1}],\n'
    '  "location_name": "",\n'
    '  "location_description": "",\n'
    '  "quest_update": "",\n'
    '  "xp_award": 0,\n'
    '  "reputation_change": [{"faction":"...","value":10}],\n'
    '  "options": ["...","...","...","...","✏ Написать свой вариант"]\n'
    "}\n"
)


class GeminiClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=90)

    async def close(self) -> None:
        await self._http.aclose()

    async def _call(
        self,
        *,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int = 4000,
        response_mime_type: str = "application/json",
    ) -> dict:
        base = settings.gemini_proxy.rstrip("/")
        url = f"{base}/v1beta/models/{model}:generateContent?key={settings.gemini_api_key}"
        headers: dict[str, str] = {}
        if settings.gemini_proxy_token:
            headers["x-proxy-token"] = settings.gemini_proxy_token
        payload: dict = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": response_mime_type,
            },
        }
        resp = await self._http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Gemini error: {data['error']}")
        return data

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            candidates = data.get("candidates")
            if not candidates:
                raise ValueError(f"No candidates in Gemini response: {list(data.keys())}")
            candidate = candidates[0]
            finish_reason = candidate.get("finishReason", "")
            if finish_reason == "SAFETY":
                raise ValueError("Gemini blocked the response (safety filter)")
            content = candidate.get("content")
            if not content:
                raise ValueError(f"No content in candidate, finishReason={finish_reason}")
            parts = content.get("parts")
            if not parts:
                raise ValueError("Empty parts in Gemini response content")
            return parts[0].get("text", "")
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Unexpected Gemini response structure: {exc}") from exc

    @staticmethod
    def _parse_plan_text(text: str) -> TurnPlan:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        raw = json.loads(text)
        return TurnPlan.model_validate(raw)

    # ── Regular turn (uses fast/flash model) ──────────────────────────

    async def generate_turn_plan(self, context: str, user_input: str) -> TurnPlan:
        prompt = (
            "КОНТЕКСТ ИГРЫ:\n"
            f"{context}\n\n"
            f"ХОД ИГРОКА:\n{user_input}\n\n"
            f"{_FORMAT_HINT}"
            "Текст вариантов короткий и реалистичный."
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                data = await self._call(
                    prompt=prompt,
                    model=settings.gemini_model,
                    temperature=0.4,
                    response_mime_type="application/json",
                )
                return self._parse_plan_text(self._extract_text(data))
            except Exception as e:
                last_error = e
                await asyncio.sleep(1 + attempt)
                log.warning("Gemini turn plan retry %s: %s", attempt + 1, e)
        raise RuntimeError(f"Failed to generate turn plan: {last_error}")

    # ── World opening (uses heavy/pro model for quality) ──────────────

    async def generate_world_opening(self, context: str, concept: str) -> TurnPlan:
        prompt = (
            "СОЗДАНИЕ МИРА И СТАРТОВОЙ СЦЕНЫ.\n\n"
            f"Игрок описал героя/сеттинг:\n{concept}\n\n"
            "КОНТЕКСТ ПЕРСОНАЖА:\n"
            f"{context}\n\n"
            "Ты — Game Master. Создай богатое, атмосферное вступление:\n"
            "- 4-6 предложений нарратива с сенсорными деталями (запахи, звуки, свет, текстуры)\n"
            "- Покажи 2-3 интерактивных объекта или NPC в стартовой сцене\n"
            "- Введи крючок квеста, который тянет игрока в историю\n"
            "- Заполни location_name и location_description для стартовой локации\n"
            "- Заполни quest_update с кратким описанием основного квеста\n"
            "- Варианты действий (options) должны быть КОНКРЕТНЫМИ для этой сцены, "
            "разными по подходу (не 4 способа осмотреться), без спойлера результата\n\n"
            f"{_FORMAT_HINT}"
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                model = settings.gemini_model_heavy if attempt < 2 else settings.gemini_model
                data = await self._call(
                    prompt=prompt,
                    model=model,
                    temperature=0.7 if attempt == 0 else 0.5,
                    max_tokens=4000,
                    response_mime_type="application/json",
                )
                return self._parse_plan_text(self._extract_text(data))
            except Exception as e:
                last_error = e
                await asyncio.sleep(1 + attempt)
                log.warning("Gemini world opening retry %s: %s", attempt + 1, e)
        raise RuntimeError(f"Failed to generate world opening: {last_error}")


def _unwrap_json_string(text: str) -> str:
    """If the model returned a JSON-encoded string, unwrap it."""
    if text.startswith('"') and text.endswith('"'):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
    return text
