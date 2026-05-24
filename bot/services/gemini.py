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
    "Верни ТОЛЬКО JSON (никакого markdown/текста вокруг) со схемой TurnPlan:\n"
    "{\n"
    '  "narrative": "3-6 предложений, БЕЗ чисел бросков и HP — их сформирует код",\n'
    '  "gm_question_mode": false,\n'
    '  "gm_answer": "",\n'
    '  "rolls": [\n'
    "    // Если игрок атакует, ОБЯЗАТЕЛЬНО заполни damage_dice и target.\n"
    "    // damage_dice — формула кости оружия (например '1d8','2d6','1d10+2').\n"
    "    // target — имя врага из scene_enemies, по кому стреляют.\n"
    '    {"type":"skill|attack|save","label":"...","ability":"STR|DEX|CON|INT|WIS|CHA","dc":12,\n'
    '     "advantage":false,"disadvantage":false,"damage_dice":"1d8",\n'
    '     "damage_type":"slashing|piercing|bludgeoning|fire|cold|lightning|poison|radiant|necrotic|psychic|thunder|acid|force",\n'
    '     "target":"Оперативник 1"}\n'
    "  ],\n"
    '  "enemy_actions": [{"name":"...","attack_bonus":4,"damage_dice":"1d6","damage_type":"piercing","reason":"..."}],\n'
    '  "direct_hp_change": 0,\n'
    "  // При добавлении оружия ВСЕГДА заполняй damage_dice и item_type=weapon|ranged.\n"
    '  "inventory_changes": [\n'
    '    {"action":"add|remove|use","name":"...","quantity":1,"damage_dice":"1d10","emoji":"🔫","item_type":"ranged"}\n'
    "  ],\n"
    '  "location_name": "",\n'
    '  "location_description": "",\n'
    '  "quest_update": "",\n'
    '  "xp_award": 0,\n'
    '  "reputation_change": [{"faction":"...","value":10}],\n'
    '  "options": ["...","...","...","...","✏ Написать свой вариант"],\n'
    "  // combat_active=true + scene_enemies=[] → конец боя. Бой вне сцены — combat_active=false.\n"
    '  "combat_active": false,\n'
    '  "scene_enemies": [\n'
    '    {"name":"Оперативник 1","hp_current":15,"hp_max":15,"ac":13,"notes":"укрытие за баком"}\n'
    "  ],\n"
    "  // Торговля. Если NPC — торговец, вручай trade_offer ОДИН раз при\n"
    "  // встрече. Дальше игрок покупает через /buy и /sell (код меняет\n"
    "  // инвентарь и золото сам). Не дублируй добавление предметов вручную.\n"
    '  "trade_offer": {\n'
    '    "npc": "Риз-оружейник",\n'
    '    "items": [\n'
    '      {"name":"Лёгкий пистолет","emoji":"🔫","item_type":"ranged","damage_dice":"1d8","price":80,"quantity":1}\n'
    "    ],\n"
    '    "buys_from_player": true,\n'
    '    "buy_back_rate": 0.5\n'
    "  },\n"
    "  // Прямое движение золота (находка кошеля, чаевые, прямая сделка вне /buy).\n"
    '  "direct_gold_change": 0,\n'
    "  // Выдача рецепта — когда игрок нашёл чертёж / его обучили.\n"
    "  // После этого рецепт доступен через /craft.\n"
    '  "grant_recipe": {\n'
    '    "name":"Аптечка","result_name":"Аптечка","result_emoji":"🧰",\n'
    '    "result_type":"consumable","result_quantity":1,\n'
    '    "components":[{"name":"Бинт","quantity":2},{"name":"Антисептик","quantity":1}],\n'
    '    "skill":"медицина","dc":10\n'
    "  },\n"
    "  // Passive Perception: если на сцене есть что-то скрытое, дай DC и\n"
    "  // что раскрыть при успехе. Код автоматически сравнит PP игрока с DC.\n"
    "  // Ставь 0 если скрытого ничего нет.\n"
    '  "passive_perception_dc": 0,\n'
    '  "passive_perception_reveal": "",\n'
    "  // Социальные броски: если NPC из известной фракции — укажи её в\n"
    "  // rolls[i].faction. Код сам подтянет репутацию и добавит бонус/штраф.\n"
    "  // Для предметов: weight_kg (вес в кг) для расчёта перегруза.\n"
    "  // requires_attunement=true для магических вещей — их бонус включится\n"
    "  // только после /attune.\n"
    "  // Универсальные способности (spells/Force/gadgets/gags — любое, что\n"
    "  // имеет заряды). Выдавай ТОЛЬКО когда игрок реально её получил.\n"
    '  "grant_ability": null,\n'
    "  // {\n"
    '  //   "name":"Толчок Силы","emoji":"✨","description":"...",\n'
    '  //   "max_uses":3,"current_uses":3,"refresh":"short|long|encounter|at_will",\n'
    '  //   "damage_dice":"2d6","damage_type":"force","heal_dice":"",\n'
    '  //   "save_ability":"STR","save_dc":13,"tags":["force","push"]\n'
    "  // }\n"
    "  // Игрок активирует через /use; ability_use — когда сам LLM описал\n"
    "  // использование способности в нарративе (редко).\n"
    '  "ability_use": null,\n'
    "  // Структурированные квесты (живут в /quests).\n"
    '  "quest_events": [\n'
    "    // {\"action\":\"create\",\"title\":\"Найти сестру\",\n"
    "    //  \"description\":\"...\",\"giver\":\"Риз\",\"is_main\":true,\n"
    "    //  \"steps\":[{\"key\":\"ask\",\"description\":\"Расспросить в баре\"}],\n"
    "    //  \"reward_xp\":100,\"reward_gold\":50}\n"
    "    // {\"action\":\"complete_step\",\"title\":\"Найти сестру\",\n"
    "    //  \"step_key_completed\":\"ask\"}\n"
    "    // {\"action\":\"complete\",\"title\":\"Найти сестру\"}\n"
    "  ],\n"
    "  // Внутриигровые напарники (не реальные игроки).\n"
    '  "add_companion": null,\n'
    "  // {\"name\":\"R2-D8\",\"role\":\"дроид-разведчик\",\n"
    "  //  \"hp_current\":18,\"hp_max\":18,\"ac\":14,\n"
    "  //  \"attack_bonus\":3,\"damage_dice\":\"1d6\",\n"
    "  //  \"initiative_bonus\":2,\"notes\":\"чинит раны в бою\"}\n"
    '  "remove_companion": ""\n'
    "}\n"
    "ПРАВИЛА:\n"
    "- НИКОГДА не пиши цифры бросков/урона/HP в narrative. Эти блоки собирает код и вставляет ДО нарратива.\n"
    "- Если идёт бой — scene_enemies должен отражать ВСЕХ живых врагов с их HP/КД.\n"
    "- Атака игрока без damage_dice и target — считается невалидной: всегда заполняй оба поля.\n"
    "- damage_type влияет на resist/immune/vulnerable — указывай тип под оружие/заклинание.\n"
    "- Если игрок Blinded/Poisoned/Prone/Restrained/Frightened — НЕ проставляй disadvantage сам, код сделает автоматически.\n"
    "- Погода/темнота тоже применяется кодом. Не дублируй их в advantage/disadvantage.\n"
    "- Combat State Machine: раунды/действие/бонус/реакцию считает код. Не пиши 'твой ход окончен' в narrative — это покажет код.\n"
    "- Торговля: используй trade_offer один раз на встречу с торговцем. Дальше покупку/продажу двигает игрок через /buy и /sell — не меняй инвентарь сам, если игрок не совершил явную сделку.\n"
    "- Крафт: grant_recipe только когда игрок реально получает знание. Сам крафт — через /craft (код спишет компоненты и бросит навык).\n"
    "- Способности: grant_ability — ТОЛЬКО когда игрок получил новое умение (сюжетно или при level-up). Дальше игрок /use — заряды и броски считает код. НЕ меняй powers сам между ходами.\n"
    "- Способности ВСЕЛЕННО-НЕЙТРАЛЬНЫЕ: spells, Force, импланты, гаджеты, трюки, песни — любое активное умение с зарядами.\n"
    "- Квесты: используй quest_events для живого журнала. active_quest_summary оставляй для совместимости, но главное — structured events в quest_events.\n"
    "- Напарники: add_companion для найма (бот-управляемый NPC), remove_companion при уходе/смерти. Напарники сражаются сами (код крутит инициативу и броски).\n"
    "- На /levelup игрок выбирает перк в отдельном диалоге — НЕ меняй abilities/HP/powers игрока вручную после level-up, это делает отдельный вызов LLM.\n"
    "- current_beat: ОБЯЗАТЕЛЬНО заполняй каждый ход — ≤80 символов, что игроку сделать прямо СЕЙЧАС, чтобы продвинуть сцену. НЕ глобальная цель квеста.\n"
    "- npc_appearances: при любом упоминании именованного NPC заполни запись (name/role/faction/attitude/notes). Без этого NPC исчезает через 20 ходов.\n"
    "- Провал броска = реальное последствие. На fail НЕ выдавай xp_award / inventory_changes.add / grant_recipe / grant_ability / quest_events.complete*. Награды только на success.\n"
    "- Не плоди роллы без ставок. Если игрок не пошёл на риск — нарративная развязка без броска.\n"
    "- Опции БЕЗ нумерации '1.' / '1)' — кнопки уже подписаны. Префикс эмодзи-тег подхода (⚡/🗣/🥷/🧠/🤝) — ок.\n"
    "- В бою (combat_active=true): максимум 2 опции из 5 — базовая атака. Остальное — обезоружить/прицел/окружение/укрытие/запугать/сдаться.\n"
    "- quest_events: cooldown — не создавай новый квест если в Active Quests уже есть похожий по теме (используй update/complete_step). deadline_turns для срочных квестов — код сам отсчитает.\n"
    "- character_setup.name (при старте) — осмысленное имя в стиле сеттинга. НЕ 'Безымянный' / 'Странник'.\n"
)

_OPENING_FORMAT_HINT = (
    "Кроме обычных полей TurnPlan, в СТАРТОВОМ ходе ОБЯЗАТЕЛЬНО заполни character_setup:\n"
    "{\n"
    '  "character_setup": {\n'
    '    "name": "...",            // имя персонажа\n'
    '    "race": "...",            // раса/вид — под сеттинг (в киберпанке нет эльфов!)\n'
    '    "char_class": "...",      // класс/архетип — под сеттинг (в кибере: нетраннер, солдат, соло)\n'
    '    "universe": "...",        // короткое название сеттинга\n'
    '    "narrative_style": "...", // серьёзно|мрачно|с юмором|нуар|...\n'
    '    "abilities": {"STR":14,"DEX":12,"CON":13,"INT":10,"WIS":10,"CHA":8},\n'
    '    "skill_proficiencies": ["скрытность","внимательность"],\n'
    '    "saving_throw_proficiencies": ["DEX","CON"],\n'
    '    "starting_inventory": [\n'
    "      // Экипировка должна быть АДЕКВАТНА сеттингу:\n"
    "      // киберпанк → пистолет/дробовик/имплант/инфочип/стимпак, НЕ меч/броня/зелье\n"
    "      // fantasy    → меч/лук/кольчуга/зелье лечения\n"
    '      {"name":"Тяжёлый пистолет","emoji":"🔫","item_type":"ranged","is_equipped":true,"damage_dice":"1d10"}\n'
    "    ]\n"
    "  }\n"
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

    # ── Adventure summary (cheap flash model, runs every 10 turns) ────

    async def summarize_adventure(self, *, prior: str, transcript: str) -> str:
        """Fold the latest transcript into a rolling one-paragraph summary.

        Keeps the Player State alive across the 20-message sliding window so
        the LLM doesn't "forget" NPC names / quest promises made 30 turns ago.
        """
        prompt = (
            "Ты — Game Master. Обнови КРАТКОЕ саммари приключения (4–8 предложений), "
            "чтобы сохранить важный контекст для следующих ходов: ключевые NPC, "
            "данные обещания, договорённости, квесты, смены локаций.\n\n"
            f"ПРЕДЫДУЩЕЕ САММАРИ (может быть пустым):\n{prior or '(пусто)'}\n\n"
            f"ПОСЛЕДНИЕ СООБЩЕНИЯ:\n{transcript}\n\n"
            "Верни ТОЛЬКО JSON вида {\"summary\": \"...\"} без markdown."
        )
        data = await self._call(
            prompt=prompt,
            model=settings.gemini_model,
            temperature=0.3,
            max_tokens=800,
            response_mime_type="application/json",
        )
        text = self._extract_text(data).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            raw = json.loads(text)
        except Exception:
            return ""
        return (raw.get("summary") or "").strip()

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
            "- ВНИМАНИЕ: экипировка, раса и класс персонажа ДОЛЖНЫ соответствовать сеттингу. "
            "Никаких мечей и эльфов в киберпанке. Никаких пистолетов в средневековом фэнтези.\n\n"
            f"{_FORMAT_HINT}\n{_OPENING_FORMAT_HINT}"
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


    # ── Level-up perk offer (universe-aware) ──────────────────────────

    async def propose_level_up(self, character, session) -> "LevelUpOffer | None":
        """Ask the LLM for 3 perk options tailored to the character's
        universe and concept. Universe-agnostic by construction — works for
        hobbits, Jedi, gingerbread men, whatever. Returns None on failure so
        the caller can fall back to the deterministic pool.
        """
        from bot.schemas import LevelUpOffer
        import json as _json

        abilities = {}
        try:
            abilities = _json.loads(character.abilities_json or "{}")
        except Exception:
            pass
        try:
            powers = _json.loads(character.powers_json or "[]")
        except Exception:
            powers = []

        prompt = (
            "LEVEL UP. Игрок только что получил уровень — подбери ему 3 перка "
            "в духе его вселенной и концепции. Перки должны быть УНИКАЛЬНЫ "
            "и тематичны: джедаю — сила, хоббиту — смекалка, вжику из "
            "«Чип и Дейл» — гаджеты, пряничному человечку — сахарные трюки.\n\n"
            f"Новый уровень: {character.level}\n"
            f"Раса: {character.race}\n"
            f"Класс/роль: {character.char_class}\n"
            f"Вселенная: {session.universe}\n"
            f"Стиль: {session.narrative_style}\n"
            f"Характеристики: {abilities}\n"
            f"Имеющиеся способности: "
            f"{[p.get('name') for p in powers]}\n\n"
            "Верни СТРОГО JSON:\n"
            "{\n"
            '  "new_level": <int>,\n'
            '  "flavor": "<короткая реплика ГМ в стиле сеттинга>",\n'
            '  "perks": [\n'
            '    {"id":"p1","label":"...","description":"...",\n'
            '     "effect_type":"stat|hp|proficiency|ability|feature",\n'
            '     "stat_key":"STR|DEX|CON|INT|WIS|CHA","stat_delta":0,\n'
            '     "hp_delta":0,"proficiency_name":"",\n'
            '     "granted_ability":{"name":"","emoji":"","description":"",\n'
            '       "max_uses":1,"current_uses":1,"refresh":"long|short|encounter|at_will",\n'
            '       "damage_dice":"","damage_type":"","heal_dice":"","save_ability":"","save_dc":0}\n'
            '    }\n'
            "  ]\n"
            "}\n"
            "Правила:\n"
            "- Ровно 3 перка, id = p1/p2/p3\n"
            "- Хотя бы 1 перк effect_type=ability (новая способность в тему вселенной)\n"
            "- effect_type=stat → не бустить одну и ту же черту дважды\n"
            "- Описание короткое, 1-2 предложения, без HTML\n"
            "- Без markdown, без комментариев, только JSON\n"
        )
        try:
            data = await self._call(
                prompt=prompt,
                model=settings.gemini_model,
                temperature=0.6,
                max_tokens=1500,
                response_mime_type="application/json",
            )
            text = self._extract_text(data).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            raw = _json.loads(text)
            return LevelUpOffer(**raw)
        except Exception as e:
            log.warning("Gemini propose_level_up failed: %s", e)
            return None


def _unwrap_json_string(text: str) -> str:
    """If the model returned a JSON-encoded string, unwrap it."""
    if text.startswith('"') and text.endswith('"'):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
    return text
