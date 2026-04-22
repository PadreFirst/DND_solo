from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Character, FactionReputation, GameSession, MessageLog, NPCState, Quest, User
from bot.schemas import EnemyAction, InventoryChange, RollRequest, TurnPlan
from bot.services import engine
from bot.services.dice import roll_dice
from bot.services.gemini import GeminiClient

log = logging.getLogger(__name__)

DEFAULT_ABILITIES = {"STR": 14, "DEX": 12, "CON": 13, "INT": 10, "WIS": 10, "CHA": 8}
DEFAULT_SKILLS = ["внимательность", "атлетика"]
DEFAULT_SAVES = ["STR", "CON"]

_NUMBERED_OPT_RE = re.compile(r"^\s*\d{1,2}\)\s*(.+)$")
_GM_PREFIX_RE = re.compile(r"^(гм|gm|мастер|вопрос)\s*:", re.IGNORECASE)


@dataclass
class TurnOutput:
    text: str
    options: list[str]


def is_gm_question(text: str) -> bool:
    """Detect GM question mode — only triggered by explicit prefixes."""
    return bool(_GM_PREFIX_RE.match((text or "").strip()))


class GameService:
    def __init__(self, gemini: GeminiClient) -> None:
        self.gemini = gemini

    async def get_or_create_user(self, db: AsyncSession, telegram_id: int, username: str | None) -> User:
        user = await db.scalar(select(User).where(User.telegram_id == telegram_id))
        if user:
            if username and user.username != username:
                user.username = username
            return user
        user = User(telegram_id=telegram_id, username=username or "", language="ru")
        db.add(user)
        await db.flush()
        return user

    async def ensure_character(self, db: AsyncSession, user: User) -> Character:
        character = await db.scalar(select(Character).where(Character.user_id == user.id))
        if character:
            return character
        character = Character(
            user_id=user.id,
            name="Странник",
            race="Человек",
            char_class="Воин",
            abilities_json=json.dumps(DEFAULT_ABILITIES, ensure_ascii=False),
            skill_proficiencies_json=json.dumps(DEFAULT_SKILLS, ensure_ascii=False),
            saving_throw_proficiencies_json=json.dumps(DEFAULT_SAVES, ensure_ascii=False),
            inventory_json=json.dumps(
                [
                    {"name": "Длинный меч", "type": "weapon", "quantity": 1, "is_equipped": True, "emoji": "⚔"},
                    {"name": "Кожаная броня", "type": "armor", "quantity": 1, "is_equipped": True, "emoji": "👕"},
                    {"name": "Зелье лечения", "type": "consumable", "quantity": 2, "is_equipped": False, "emoji": "🧪"},
                ],
                ensure_ascii=False,
            ),
            equipment_json=json.dumps(
                {
                    "body": {"name": "Кожаная броня", "emoji": "👕"},
                    "weapon_1": {"name": "Длинный меч", "emoji": "⚔"},
                },
                ensure_ascii=False,
            ),
            class_features_json=json.dumps(
                [
                    {"name": "Второе дыхание", "emoji": "💨", "description": "Раз в короткий отдых восстанови 1d10+уровень HP."}
                ],
                ensure_ascii=False,
            ),
        )
        db.add(character)
        await db.flush()
        return character

    async def ensure_session(self, db: AsyncSession, user: User) -> GameSession:
        gs = await db.scalar(select(GameSession).where(GameSession.user_id == user.id))
        if gs:
            return gs
        gs = GameSession(
            user_id=user.id,
            universe="custom",
            narrative_style="серьёзный",
        )
        db.add(gs)
        await db.flush()
        return gs

    async def save_message(self, db: AsyncSession, user_id: int, role: str, content: str) -> None:
        db.add(MessageLog(user_id=user_id, role=role, content=content))
        await db.flush()

    async def get_recent_messages(self, db: AsyncSession, user_id: int, limit: int = 20) -> list[MessageLog]:
        rows = await db.scalars(
            select(MessageLog)
            .where(MessageLog.user_id == user_id)
            .order_by(desc(MessageLog.created_at))
            .limit(limit)
        )
        return list(reversed(list(rows)))

    async def build_context(self, db: AsyncSession, user: User, ch: Character, gs: GameSession) -> str:
        msgs = await self.get_recent_messages(db, user.id, 20)
        abilities = json.loads(ch.abilities_json or "{}")
        recent = "\n".join(f"{m.role.upper()}: {m.content[:400]}" for m in msgs) or "(пусто)"
        return (
            f"Player: {ch.name} ({ch.race} {ch.char_class}, level {ch.level})\n"
            f"HP: {ch.hp_current}/{ch.hp_max} temp:{ch.temp_hp} AC:{ch.ac} gold:{ch.gold}\n"
            f"Abilities: {abilities}\n"
            f"Skills: {json.loads(ch.skill_proficiencies_json or '[]')}\n"
            f"Conditions: {json.loads(ch.conditions_json or '[]')}\n"
            f"Location: {gs.current_location}\n"
            f"Location Description: {gs.current_location_description}\n"
            f"Quest: {gs.active_quest_summary}\n"
            f"Universe: {gs.universe}; Style: {gs.narrative_style}; Weather:{gs.weather}; Time:{gs.time_of_day}\n"
            f"Recent Messages:\n{recent}"
        )

    @staticmethod
    def _ensure_options(options: list[str]) -> list[str]:
        clean = [o.strip() for o in options if o and o.strip()]
        clean = clean[:5]
        if len(clean) < 3:
            clean = ["Осмотреться", "Действовать осторожно", "Поговорить с NPC"]
        write_option = "✏ Написать свой вариант"
        if not any(o.startswith("✏") for o in clean):
            if len(clean) >= 5:
                clean[-1] = write_option
            else:
                clean.append(write_option)
        return clean[:5]

    @staticmethod
    def _parse_numbered_options(text: str) -> list[str]:
        """Extract numbered options like '1) ...' from text."""
        opts: list[str] = []
        for line in text.splitlines():
            m = _NUMBERED_OPT_RE.match(line)
            if m:
                opts.append(m.group(1).strip())
        return opts

    @staticmethod
    def _strip_numbered_options(text: str) -> str:
        """Remove numbered option lines from narrative text."""
        lines = [ln for ln in text.splitlines() if not _NUMBERED_OPT_RE.match(ln)]
        return "\n".join(lines).strip()

    @staticmethod
    def _fallback_opening(concept: str) -> TurnPlan:
        return TurnPlan(
            narrative=(
                f"Ты делаешь первый шаг в новую историю. {concept[:220]}.\n"
                "Ветер с тракта приносит запах дождя и дыма. "
                "У ворот ржавый фонарь покачивается на цепи, бросая неровные тени на мостовую.\n"
                "У стены таверны два наёмника жарко спорят о пропавшем караване, "
                "а хозяин, вытирая стойку, косится на тебя с интересом.\n"
                "На доске объявлений свежая записка: «Разыскиваются смельчаки. Руины Мориана. Щедрая награда.»"
            ),
            location_name="Постоялый двор «Три фонаря»",
            location_description="Каменное здание на перепутье двух трактов. Внутри тепло и шумно, пахнет элем и жареным мясом.",
            quest_update="Узнать о руинах Мориана и найти заказчика.",
            options=[
                "Подойти к наёмникам и прислушаться к спору",
                "Поговорить с хозяином таверны",
                "Прочитать объявление на доске",
                "Осмотреть зал и выходы",
            ],
        )

    def _fallback_turn_plan(self, player_input: str, gs: GameSession) -> TurnPlan:
        text = (player_input or "").strip().lower()
        options = self._ensure_options([
            "Осмотреть окружение внимательнее",
            "Поговорить с NPC и собрать слухи",
            "Продвинуться к цели квеста",
            "Подготовить снаряжение к риску",
        ])

        if is_gm_question(player_input):
            return TurnPlan(
                narrative="",
                gm_question_mode=True,
                gm_answer=(
                    "Смотри по ситуации: сначала определяется намерение, потом код проверяет валидность действия "
                    "(ресурсы, дистанция, доступные действия), и только после этого выполняются броски и изменения стейта."
                ),
                options=options,
            )

        if any(k in text for k in ("атак", "удар", "бью", "стреля")):
            return TurnPlan(
                narrative="Ты резко переходишь к атаке, и сцена мгновенно накаляется.",
                rolls=[RollRequest(type="attack", label="ближняя атака", ability="STR", dc=12)],
                enemy_actions=[EnemyAction(name="Враг отвечает", attack_bonus=3, damage_dice="1d6", reason="контратака")],
                options=options,
            )
        if any(k in text for k in ("зелье", "леч", "выпью")):
            return TurnPlan(
                narrative="Ты быстро используешь лечебный ресурс, стараясь не терять инициативу.",
                direct_hp_change=8,
                inventory_changes=[InventoryChange(action="use", name="Зелье лечения", quantity=1)],
                options=options,
            )
        if any(k in text for k in ("отдых", "передох", "short rest", "long rest")):
            return TurnPlan(
                narrative="Ты находишь короткую передышку и приводишь дыхание в порядок.",
                direct_hp_change=5,
                options=options,
            )
        if any(k in text for k in ("провер", "осмотр", "ищу", "вниматель")):
            return TurnPlan(
                narrative=f"Ты внимательно исследуешь место: {gs.current_location}.",
                rolls=[RollRequest(type="skill", label="внимательность", ability="WIS", dc=12)],
                options=options,
            )

        return TurnPlan(
            narrative="Ты действуешь аккуратно, сохраняя контроль над ситуацией.",
            options=options,
        )

    @staticmethod
    def format_character_intro(ch: Character) -> str:
        inv = json.loads(ch.inventory_json or "[]")
        items = ", ".join(
            f"{it.get('emoji', '•')} {it['name']}" + (f" ×{it['quantity']}" if int(it.get("quantity", 1)) > 1 else "")
            for it in inv
        ) or "пусто"
        return (
            f"👤 <b>{ch.name}</b>, {ch.race} {ch.char_class} (ур. {ch.level})\n"
            f"♥ HP: {ch.hp_current}/{ch.hp_max} | КД: {ch.ac} | Золото: {ch.gold}\n"
            f"🎒 {items}"
        )

    async def initialize_story(self, db: AsyncSession, user: User, concept: str) -> TurnOutput:
        ch = await self.ensure_character(db, user)
        gs = await self.ensure_session(db, user)
        context = await self.build_context(db, user, ch, gs)

        try:
            plan = await self.gemini.generate_world_opening(context=context, concept=concept)
        except Exception:
            log.exception("Gemini world opening failed, using fallback")
            plan = self._fallback_opening(concept)

        narrative = plan.narrative.strip() or "Ты делаешь первый шаг в новую историю..."
        options = self._ensure_options(plan.options)

        if plan.location_name:
            gs.current_location = plan.location_name
        if plan.location_description:
            gs.current_location_description = plan.location_description
        if plan.quest_update:
            gs.active_quest_summary = plan.quest_update

        gs.last_options_json = json.dumps(options, ensure_ascii=False)
        gs.turn_number = 1

        char_intro = self.format_character_intro(ch)
        full_text = f"{char_intro}\n\n---\n\n{narrative}"
        await self.save_message(db, user.id, "assistant", narrative)
        return TurnOutput(text=full_text, options=options)

    async def process_turn(self, db: AsyncSession, user: User, player_input: str) -> TurnOutput:
        ch = await self.ensure_character(db, user)
        gs = await self.ensure_session(db, user)
        gs.turn_number += 1
        await self.save_message(db, user.id, "user", player_input)

        context = await self.build_context(db, user, ch, gs)
        try:
            plan: TurnPlan = await self.gemini.generate_turn_plan(context=context, user_input=player_input)
        except Exception:
            log.exception("Gemini turn plan failed, using fallback")
            plan = self._fallback_turn_plan(player_input, gs)

        mechanics_lines: list[str] = []

        if plan.gm_question_mode:
            answer = (plan.gm_answer or "Разберем это кратко по шагам.").strip()
            options = self._ensure_options(plan.options or json.loads(gs.last_options_json or "[]"))
            gs.last_options_json = json.dumps(options, ensure_ascii=False)
            text = f"💡 {answer}\n\n---\nСитуация: {gs.current_location}\n{gs.current_location_description}"
            await self.save_message(db, user.id, "assistant", text)
            return TurnOutput(text=text, options=options)

        for rr in plan.rolls:
            if rr.type == "skill":
                rich = engine.make_skill_check(ch, rr.label, rr.dc, advantage=rr.advantage, disadvantage=rr.disadvantage)
                mechanics_lines.append(rich.format(kind="Проверка"))
            elif rr.type == "attack":
                rich = engine.make_attack_roll(
                    ch, rr.dc, ability_key=(rr.ability or "STR"),
                    advantage=rr.advantage, disadvantage=rr.disadvantage, label=rr.label or "атака",
                )
                mechanics_lines.append(rich.format(kind="Атака"))
            elif rr.type == "save":
                rich = engine.make_save_roll(ch, rr.ability or "CON", rr.dc, advantage=rr.advantage, disadvantage=rr.disadvantage)
                mechanics_lines.append(rich.format(kind="Спасбросок"))

        for ea in plan.enemy_actions:
            atk_d20 = random.randint(1, 20)
            atk_total = atk_d20 + ea.attack_bonus
            hit = atk_total >= ch.ac
            mechanics_lines.append(
                f"🎲 {ea.name}: d20={atk_d20}, бонус {ea.attack_bonus:+d} → {atk_total} vs КД {ch.ac} — "
                f"{'Попадание' if hit else 'Промах'}"
            )
            if hit and ea.damage_dice:
                dmg = roll_dice(ea.damage_dice)
                old, new = engine.apply_hp_change(ch, -dmg.total)
                mechanics_lines.append(f"♥ HP: {old} → {new} (урон {dmg.total})")

        if plan.direct_hp_change != 0:
            old, new = engine.apply_hp_change(ch, plan.direct_hp_change)
            mechanics_lines.append(f"♥ HP: {old} → {new}")

        if plan.inventory_changes:
            inv = json.loads(ch.inventory_json or "[]")
            for change in plan.inventory_changes:
                if change.action == "add":
                    inv.append({"name": change.name, "quantity": change.quantity, "type": "misc", "is_equipped": False})
                    mechanics_lines.append(f"🎒 Добавлено: {change.name} x{change.quantity}")
                elif change.action in {"remove", "use"}:
                    for item in inv:
                        if item.get("name", "").lower() == change.name.lower():
                            item["quantity"] = max(0, int(item.get("quantity", 1)) - change.quantity)
                            mechanics_lines.append(f"🎒 Использовано: {change.name} x{change.quantity}")
                    inv = [i for i in inv if int(i.get("quantity", 1)) > 0]
            ch.inventory_json = json.dumps(inv, ensure_ascii=False)

        if plan.location_name:
            gs.current_location = plan.location_name
        if plan.location_description:
            gs.current_location_description = plan.location_description
        if plan.quest_update:
            gs.active_quest_summary = plan.quest_update
        if plan.xp_award:
            ch.xp_current += plan.xp_award
            mechanics_lines.append(f"⭐ +{plan.xp_award} XP")
            while ch.xp_current >= ch.xp_to_next_level:
                ch.level += 1
                ch.xp_to_next_level += 300 + (ch.level - 1) * 200
                ch.hp_max += 6 + max(1, ch.ability_mod("CON"))
                ch.hp_current = ch.hp_max
                ch.proficiency_bonus = 2 + max(0, (ch.level - 1) // 4)
                mechanics_lines.append(f"🎉 Новый уровень: {ch.level}")

        for rep in plan.reputation_change:
            fr = await db.scalar(
                select(FactionReputation)
                .where(FactionReputation.user_id == user.id, FactionReputation.faction_name == rep.faction)
            )
            if not fr:
                fr = FactionReputation(user_id=user.id, faction_name=rep.faction, reputation_score=0)
                db.add(fr)
                await db.flush()
            old_rep = fr.reputation_score
            fr.reputation_score = max(-100, min(100, fr.reputation_score + rep.value))
            mechanics_lines.append(f"📊 Репутация {rep.faction}: {old_rep} → {fr.reputation_score}")

        if ch.hp_current <= 0:
            mechanics_lines.append("💀 Персонаж без сознания. Нужны спасброски смерти.")

        options = self._ensure_options(plan.options)
        gs.last_options_json = json.dumps(options, ensure_ascii=False)
        body = plan.narrative.strip() or "..."
        state_block = "\n".join(mechanics_lines).strip()
        text = body if not state_block else f"{body}\n\n{state_block}"
        await self.save_message(db, user.id, "assistant", text)
        return TurnOutput(text=text, options=options)

    async def build_character_api_payload(self, db: AsyncSession, telegram_id: int) -> dict:
        user = await db.scalar(select(User).where(User.telegram_id == telegram_id))
        if not user:
            raise ValueError("User not found")
        ch = await self.ensure_character(db, user)
        gs = await self.ensure_session(db, user)
        quests = list(await db.scalars(select(Quest).where(Quest.user_id == user.id)))
        factions = list(await db.scalars(select(FactionReputation).where(FactionReputation.user_id == user.id)))
        npcs = list(await db.scalars(select(NPCState).where(NPCState.user_id == user.id)))

        return {
            "character": {
                "name": ch.name,
                "race": ch.race,
                "class": ch.char_class,
                "level": ch.level,
                "universe": gs.universe,
                "narrative_style": gs.narrative_style,
                "xp_current": ch.xp_current,
                "xp_to_next_level": ch.xp_to_next_level,
                "hp_current": ch.hp_current,
                "hp_max": ch.hp_max,
                "temp_hp": ch.temp_hp,
                "ac": ch.ac,
                "speed": ch.speed_m,
                "proficiency_bonus": ch.proficiency_bonus,
                "gold": ch.gold,
                "rest_status": json.loads(ch.rest_status_json or "{}"),
            },
            "abilities": json.loads(ch.abilities_json or "{}"),
            "skills": [{"name": s, "proficient": True} for s in json.loads(ch.skill_proficiencies_json or "[]")],
            "saving_throws": {k: k in json.loads(ch.saving_throw_proficiencies_json or "[]") for k in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]},
            "conditions": json.loads(ch.conditions_json or "[]"),
            "spell_slots": json.loads(ch.spell_slots_json or "{}"),
            "known_spells": json.loads(ch.known_spells_json or "[]"),
            "class_features": json.loads(ch.class_features_json or "[]"),
            "proficiencies": {
                "skills": json.loads(ch.skill_proficiencies_json or "[]"),
                "saves": json.loads(ch.saving_throw_proficiencies_json or "[]"),
            },
            "equipment": json.loads(ch.equipment_json or "{}"),
            "attunement": json.loads(ch.attunement_json or '{"max":3,"items":[]}'),
            "inventory": json.loads(ch.inventory_json or "[]"),
            "known_recipes": json.loads(ch.known_recipes_json or "[]"),
            "quests": {
                "active": [
                    {
                        "quest_id": q.id,
                        "title": q.title,
                        "is_main": q.is_main,
                        "description": q.description,
                        "giver": q.giver,
                        "steps": json.loads(q.steps_json or "[]"),
                        "rewards": {"xp": q.reward_xp, "gold": q.reward_gold},
                    }
                    for q in quests
                    if q.status == "active"
                ],
                "completed": [{"quest_id": q.id, "title": q.title} for q in quests if q.status == "completed"],
            },
            "location": {
                "name": gs.current_location,
                "description": gs.current_location_description,
                "time_of_day": gs.time_of_day,
                "weather": gs.weather,
                "npcs": [
                    {
                        "name": n.name,
                        "attitude": n.attitude,
                        "faction": n.notes or "",
                        "is_merchant": bool(json.loads(n.inventory_json or "[]")),
                    }
                    for n in npcs
                    if n.current_location == gs.current_location
                ],
            },
            "factions": [{"name": f.faction_name, "score": f.reputation_score} for f in factions],
            "adventure_summary": gs.adventure_summary,
        }
