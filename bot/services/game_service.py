from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Character, FactionReputation, GameSession, MessageLog, NPCState, Quest, User
from bot.schemas import (
    CharacterSetup,
    EnemyAction,
    InventoryChange,
    Recipe,
    RecipeComponent,
    RollRequest,
    SceneEnemy,
    StartingItem,
    TradeItem,
    TradeOffer,
    TurnPlan,
)
from bot.services import engine
from bot.services.dice import roll_dice
from bot.services.gemini import GeminiClient

log = logging.getLogger(__name__)

DEFAULT_ABILITIES = {"STR": 14, "DEX": 12, "CON": 13, "INT": 10, "WIS": 10, "CHA": 8}
DEFAULT_SKILLS = ["внимательность", "атлетика"]
DEFAULT_SAVES = ["STR", "CON"]

# Items in inventory_json use this shape. Keep in sync with StartingItem.
# `damage_dice` is what shows up in /inventory and drives damage rolls when
# the player attacks — without it the player sees only the item name.

_NUMBERED_OPT_RE = re.compile(r"^\s*\d{1,2}\)\s*(.+)$")
_GM_PREFIX_RE = re.compile(r"^(гм|gm|мастер|вопрос)\s*:", re.IGNORECASE)

# How often to (re-)generate a compact summary of the adventure. Runs as a
# background task so the player never waits for it.
_SUMMARY_EVERY_N_TURNS = 10


def _has_cond(character: Character, name: str) -> bool:
    try:
        data = json.loads(character.conditions_json or "[]")
    except Exception:
        return False
    low = name.lower()
    for c in data:
        cn = c if isinstance(c, str) else (c.get("name") or c.get("id") or "")
        if str(cn).lower() == low:
            return True
    return False


def _add_cond(character: Character, name: str) -> None:
    if _has_cond(character, name):
        return
    data = json.loads(character.conditions_json or "[]")
    data.append(name)
    character.conditions_json = json.dumps(data, ensure_ascii=False)


def _remove_cond(character: Character, name: str) -> None:
    data = json.loads(character.conditions_json or "[]")
    low = name.lower()
    kept = [
        c for c in data
        if str(c if isinstance(c, str) else c.get("name", "")).lower() != low
    ]
    character.conditions_json = json.dumps(kept, ensure_ascii=False)


def _find_scene_target(scene: list[dict], target_name: str) -> int | None:
    """Match attack target to a scene enemy. Tolerant to typos / word order.

    Returns the first matching index, or the first LIVING enemy if `target_name`
    is empty. Returns None if nothing sensible to hit.
    """
    alive = [i for i, e in enumerate(scene) if int(e.get("hp_current", 0) or 0) > 0]
    if not alive:
        return None
    if not target_name:
        return alive[0]
    needle = target_name.strip().lower()
    for i in alive:
        name = (scene[i].get("name") or "").lower()
        if name and (needle in name or name in needle):
            return i
    return alive[0]


def _format_inventory_item(it: dict, *, short: bool) -> str:
    """Render a single inventory entry for the chat.

    short=True → intro line ("⚔ Пистолет ×1"). Used in character card.
    short=False → /inventory line with damage formula and equip marker.
    """
    name = it.get("name", "?")
    emoji = it.get("emoji", "•")
    qty = int(it.get("quantity", 1) or 1)
    dmg = it.get("damage_dice") or ""
    equipped = bool(it.get("is_equipped"))

    parts = [f"{emoji} {name}"]
    if qty > 1:
        parts.append(f"×{qty}")
    if dmg:
        parts.append(f"[урон {dmg}]")
    if equipped and not short:
        parts.append("(экип.)")
    return " ".join(parts)


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
        """Return the player character, creating a *blank* one if absent.

        Previously this seeded a medieval fighter (long sword, leather armor,
        healing potions). That was wrong in non-fantasy settings —
        cyberpunk / sci-fi players were handed swords. Now we just create a
        shell; `initialize_story` fills the gear based on the chosen
        universe (via `character_setup` from the LLM, or a generic fallback).
        """
        character = await db.scalar(select(Character).where(Character.user_id == user.id))
        if character:
            return character
        character = Character(
            user_id=user.id,
            name="Безымянный",
            race="",
            char_class="",
            abilities_json=json.dumps(DEFAULT_ABILITIES, ensure_ascii=False),
            skill_proficiencies_json=json.dumps(DEFAULT_SKILLS, ensure_ascii=False),
            saving_throw_proficiencies_json=json.dumps(DEFAULT_SAVES, ensure_ascii=False),
            inventory_json="[]",
            equipment_json="{}",
            class_features_json="[]",
        )
        db.add(character)
        await db.flush()
        return character

    @staticmethod
    def _apply_character_setup(ch: Character, gs: GameSession, setup: CharacterSetup) -> None:
        """Overwrite blank character fields from the LLM-generated setup."""
        if setup.name:
            ch.name = setup.name[:120]
        if setup.race:
            ch.race = setup.race[:80]
        if setup.char_class:
            ch.char_class = setup.char_class[:80]
        if setup.abilities:
            merged = DEFAULT_ABILITIES | {
                k.upper(): int(v) for k, v in setup.abilities.items() if k.upper() in DEFAULT_ABILITIES
            }
            ch.abilities_json = json.dumps(merged, ensure_ascii=False)
        if setup.skill_proficiencies:
            ch.skill_proficiencies_json = json.dumps(
                [s.strip().lower() for s in setup.skill_proficiencies if s.strip()], ensure_ascii=False
            )
        if setup.saving_throw_proficiencies:
            ch.saving_throw_proficiencies_json = json.dumps(
                [s.strip().upper() for s in setup.saving_throw_proficiencies if s.strip()], ensure_ascii=False
            )
        if setup.starting_inventory:
            inv = []
            equip: dict = {}
            for it in setup.starting_inventory:
                item = {
                    "name": it.name,
                    "emoji": it.emoji or "•",
                    "type": it.item_type or "misc",
                    "quantity": max(1, int(it.quantity)),
                    "is_equipped": bool(it.is_equipped),
                }
                if it.damage_dice:
                    item["damage_dice"] = it.damage_dice
                inv.append(item)
                if it.is_equipped:
                    slot = it.item_type or "misc"
                    equip[slot] = {"name": it.name, "emoji": it.emoji or "•"}
            ch.inventory_json = json.dumps(inv, ensure_ascii=False)
            if equip:
                ch.equipment_json = json.dumps(equip, ensure_ascii=False)
        if setup.universe:
            gs.universe = setup.universe[:255]
        if setup.narrative_style:
            gs.narrative_style = setup.narrative_style[:80]

    @staticmethod
    def _fallback_character_setup(concept: str) -> CharacterSetup:
        """Used only when the LLM failed to produce character_setup AND we
        can't tell what universe the player picked. Generic human fighter.
        """
        return CharacterSetup(
            name="Странник",
            race="Человек",
            char_class="Воин",
            abilities={"STR": 15, "DEX": 13, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8},
            skill_proficiencies=list(DEFAULT_SKILLS),
            saving_throw_proficiencies=list(DEFAULT_SAVES),
            starting_inventory=[
                StartingItem(name="Длинный меч", emoji="⚔", item_type="weapon", is_equipped=True, damage_dice="1d8"),
                StartingItem(name="Кожаная броня", emoji="👕", item_type="armor", is_equipped=True),
                StartingItem(name="Зелье лечения", emoji="🧪", item_type="consumable", quantity=2),
            ],
        )

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
        items = ", ".join(_format_inventory_item(it, short=True) for it in inv) or "пусто"
        bits = [f"👤 <b>{ch.name}</b>"]
        tail = " ".join(x for x in (ch.race, ch.char_class) if x)
        if tail:
            bits[0] += f", {tail}"
        bits[0] += f" (ур. {ch.level})"
        return (
            f"{bits[0]}\n"
            f"♥ HP: {ch.hp_current}/{ch.hp_max} | КД: {ch.ac} | Золото: {ch.gold}\n"
            f"🎒 {items}"
        )

    @staticmethod
    def format_inventory_detailed(ch: Character) -> str:
        inv = json.loads(ch.inventory_json or "[]")
        if not inv:
            return "🎒 <b>Инвентарь пуст.</b>"
        lines = ["🎒 <b>Инвентарь</b>"]
        for it in inv:
            lines.append(" • " + _format_inventory_item(it, short=False))
        lines.append(f"\n💰 Золото: {ch.gold}")
        return "\n".join(lines)

    @staticmethod
    def format_stats(ch: Character) -> str:
        abilities = json.loads(ch.abilities_json or "{}")
        ab_line = " ".join(
            f"{k} {v} ({(int(v) - 10) // 2:+d})"
            for k, v in abilities.items()
        )
        skills = ", ".join(json.loads(ch.skill_proficiencies_json or "[]")) or "—"
        saves = ", ".join(json.loads(ch.saving_throw_proficiencies_json or "[]")) or "—"
        conditions = json.loads(ch.conditions_json or "[]")
        cond_line = ", ".join(c if isinstance(c, str) else c.get("name", "?") for c in conditions) or "нет"
        return (
            f"📊 <b>{ch.name}</b> ({ch.race} {ch.char_class}, ур. {ch.level})\n"
            f"♥ HP: {ch.hp_current}/{ch.hp_max}  ⛨ КД: {ch.ac}  💨 Скорость: {ch.speed_m}м\n"
            f"⭐ XP: {ch.xp_current}/{ch.xp_to_next_level}  🎯 PB: +{ch.proficiency_bonus}  💰 Золото: {ch.gold}\n\n"
            f"<b>Характеристики</b>: {ab_line}\n"
            f"<b>Владения (навыки)</b>: {skills}\n"
            f"<b>Владения (спасброски)</b>: {saves}\n"
            f"<b>Состояния</b>: {cond_line}"
        )

    @staticmethod
    async def format_active_quest(db: AsyncSession, user_id: int, gs: GameSession) -> str:
        quests = list(await db.scalars(
            select(Quest).where(Quest.user_id == user_id, Quest.status == "active")
        ))
        if not quests and not gs.active_quest_summary:
            return "📋 Активных квестов нет."
        out = ["📋 <b>Активные квесты</b>"]
        for q in quests:
            tag = "⭐ " if q.is_main else ""
            out.append(f"\n{tag}<b>{q.title}</b>")
            if q.description:
                out.append(q.description)
            for step in json.loads(q.steps_json or "[]"):
                mark = "✅" if step.get("completed") else "⬜"
                out.append(f"  {mark} {step.get('text', '')}")
            if q.giver:
                out.append(f"<i>От: {q.giver}</i>")
        if gs.active_quest_summary and not quests:
            out.append(gs.active_quest_summary)
        return "\n".join(out)

    @staticmethod
    def _find_weapon_damage(ch: Character, label: str) -> tuple[str, int]:
        """Best-effort: match an attack label against inventory to pick the
        weapon's damage dice. Returns (dice_expr, ability_mod) — ability mod
        is STR for melee-looking labels, DEX for ranged/finesse-looking
        labels. If nothing matches, returns ("", 0).
        """
        if not label:
            return "", 0
        low = label.lower()
        inv = json.loads(ch.inventory_json or "[]")
        weapon = None
        for it in inv:
            if it.get("type") in ("weapon", "ranged") and it.get("is_equipped"):
                name = (it.get("name") or "").lower()
                if name and (name in low or low in name or any(w in low for w in name.split())):
                    weapon = it
                    break
        if weapon is None:
            # Fallback: first equipped weapon
            for it in inv:
                if it.get("type") in ("weapon", "ranged") and it.get("is_equipped"):
                    weapon = it
                    break
        if weapon is None:
            return "", 0
        dice = weapon.get("damage_dice") or ""
        ability = "DEX" if any(k in (weapon.get("name") or "").lower() for k in (
            "пистолет", "винтовк", "лук", "арбалет", "дротик", "кинжал", "мет", "снайпер"
        )) else "STR"
        return dice, engine.ability_mod(ch, ability)

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

        # Character creation FIRST — the intro line we send back should
        # reflect the generated character, not a leftover blank shell.
        setup = plan.character_setup or self._fallback_character_setup(concept)
        self._apply_character_setup(ch, gs, setup)

        if plan.location_name:
            gs.current_location = plan.location_name
        if plan.location_description:
            gs.current_location_description = plan.location_description
        if plan.quest_update:
            gs.active_quest_summary = plan.quest_update

        # Opening scene may already include hostile NPCs — surface them.
        if plan.combat_active and plan.scene_enemies:
            gs.combat_active = True
            gs.scene_state_json = json.dumps(
                [e.model_dump() for e in plan.scene_enemies], ensure_ascii=False
            )
        else:
            gs.combat_active = False
            gs.scene_state_json = "[]"

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

        # ── Death-save loop short-circuits the turn entirely ──
        # If the character is already unconscious and not stabilized/dead,
        # we skip the LLM and just roll a death save. This matches the TZ
        # exactly: "При HP=0 персонаж без сознания, каждый ход бросает 1d20".
        if ch.hp_current == 0 and not _has_cond(ch, "dead") and not _has_cond(ch, "stabilized"):
            return await self._handle_death_save_turn(db, user, ch, gs)

        context = await self.build_context(db, user, ch, gs)
        try:
            plan: TurnPlan = await self.gemini.generate_turn_plan(context=context, user_input=player_input)
        except Exception:
            log.exception("Gemini turn plan failed, using fallback")
            plan = self._fallback_turn_plan(player_input, gs)

        # GM-question short-circuits — no mechanics, no scene changes.
        if plan.gm_question_mode:
            answer = (plan.gm_answer or "Разберем это кратко по шагам.").strip()
            options = self._ensure_options(plan.options or json.loads(gs.last_options_json or "[]"))
            gs.last_options_json = json.dumps(options, ensure_ascii=False)
            text = f"💡 {answer}\n\n---\nСитуация: {gs.current_location}\n{gs.current_location_description}"
            await self.save_message(db, user.id, "assistant", text)
            return TurnOutput(text=text, options=options)

        # Load / reset scene enemies. If the LLM declared a new combat scene
        # we overwrite; otherwise we keep whatever was active (so the engine
        # can deplete HP across turns).
        scene: list[dict] = json.loads(gs.scene_state_json or "[]")
        was_in_combat = bool(gs.combat_active)
        if plan.scene_enemies:
            scene = [e.model_dump() for e in plan.scene_enemies]
        if plan.combat_active:
            gs.combat_active = True

        # Combat state machine: first turn that flips into combat rolls
        # initiative once for player + every enemy. Subsequent turns just
        # advance the round counter after the player acts.
        combat_started_now = False
        if gs.combat_active and scene and not was_in_combat:
            engine.start_combat(gs, ch, scene)
            combat_started_now = True

        # === PRE-NARRATIVE mechanics (goes BEFORE the story text) ===
        pre_lines: list[str] = []

        if gs.combat_active and scene:
            if combat_started_now:
                pre_lines.append("⚔ Начинается бой! Инициатива брошена.")
            pre_lines.append(engine.format_combat_status(gs))
            enemies_line = " | ".join(
                f"{e.get('name', '?')} (HP {e.get('hp_current', '?')}/{e.get('hp_max', '?')}, КД {e.get('ac', '?')})"
                for e in scene
            )
            pre_lines.append(f"⚔ Враги на сцене: {enemies_line}")

        for rr in plan.rolls:
            if rr.type == "skill":
                rich = engine.make_skill_check(
                    ch, rr.label, rr.dc,
                    advantage=rr.advantage, disadvantage=rr.disadvantage,
                    gs=gs,
                )
                pre_lines.append(rich.format(kind="Проверка"))
            elif rr.type == "attack":
                # Resolve weapon damage dice. Priority: explicit `damage_dice`
                # from the LLM → match weapon in inventory → no damage at all.
                dmg_expr = (rr.damage_dice or "").strip()
                ability_key = (rr.ability or "").upper() or None
                if not dmg_expr:
                    dmg_expr, ab_mod_for_dmg = self._find_weapon_damage(ch, rr.label)
                else:
                    ab_mod_for_dmg = engine.ability_mod(ch, ability_key or "STR")
                if ability_key is None:
                    ability_key = "STR"

                # Hard check: если оружия в инвентаре нет И LLM не дала
                # damage_dice — это невалидная атака. Показываем честно.
                if not dmg_expr:
                    pre_lines.append(
                        f"⚠ Атака '{rr.label}': нет подходящего оружия в руках — бросок не делаем."
                    )
                    continue

                # Hard check (combat state machine): одна атака = одно
                # действие за раунд. Повторная атака в том же раунде
                # отбрасывается с явным сообщением — это предсказуемая
                # механика, а не "LLM решила так".
                if gs.combat_active and gs.action_used:
                    pre_lines.append(
                        f"⚠ Атака '{rr.label}': действие уже потрачено в этом раунде."
                    )
                    continue
                if gs.combat_active:
                    gs.action_used = True

                rich = engine.make_attack_roll(
                    ch, rr.dc, ability_key=ability_key,
                    advantage=rr.advantage, disadvantage=rr.disadvantage,
                    label=rr.label or "атака",
                    gs=gs,
                )
                pre_lines.append(rich.format(kind="Атака"))

                if rich.success and dmg_expr:
                    # Crit on nat20 (on the chosen d20 after advantage/disadvantage).
                    chosen_d20 = rich.d20 if rich.d20_alt is None else (
                        max(rich.d20, rich.d20_alt) if rich.advantage else min(rich.d20, rich.d20_alt)
                    )
                    crit = chosen_d20 == 20
                    dmg_total, dmg_detail = engine.roll_damage(
                        dmg_expr, ability_mod_value=ab_mod_for_dmg, critical=crit,
                    )
                    pre_lines.append(f"💥 Урон: {dmg_detail}")

                    # Apply to the named target if we can find it, otherwise
                    # the first living enemy. Prevents "я стрелял, но никто
                    # не умер" confusion.
                    target_idx = _find_scene_target(scene, rr.target)
                    if target_idx is not None:
                        entry = scene[target_idx]
                        hp_before = int(entry.get("hp_current", 0) or 0)
                        hp_after = max(0, hp_before - dmg_total)
                        entry["hp_current"] = hp_after
                        pre_lines.append(
                            f"♥ {entry.get('name', 'Враг')}: {hp_before} → {hp_after}"
                        )
                        if hp_after == 0:
                            pre_lines.append(f"☠ {entry.get('name', 'Враг')} повержен.")
            elif rr.type == "save":
                rich = engine.make_save_roll(
                    ch, rr.ability or "CON", rr.dc,
                    advantage=rr.advantage, disadvantage=rr.disadvantage,
                    gs=gs,
                )
                pre_lines.append(rich.format(kind="Спасбросок"))

        for ea in plan.enemy_actions:
            atk_d20 = random.randint(1, 20)
            atk_total = atk_d20 + ea.attack_bonus
            hit = atk_total >= ch.ac
            pre_lines.append(
                f"🎲 {ea.name}: d20={atk_d20}, бонус {ea.attack_bonus:+d} → {atk_total} vs КД {ch.ac} — "
                f"{'Попадание' if hit else 'Промах'}"
            )
            if hit and ea.damage_dice:
                dmg = roll_dice(ea.damage_dice)
                old, new = engine.apply_damage(ch, -dmg.total, damage_type=ea.damage_type or "")
                applied = old - new
                type_tag = f" ({ea.damage_type})" if ea.damage_type else ""
                if applied != dmg.total:
                    # Resist/vuln/immune took effect — surface it so the
                    # player understands why they took more/less.
                    pre_lines.append(
                        f"♥ HP: {old} → {new} (урон {dmg.total}{type_tag} → применено {applied})"
                    )
                else:
                    pre_lines.append(f"♥ HP: {old} → {new} (урон {dmg.total}{type_tag})")
                if ch.hp_current == 0:
                    _add_cond(ch, "unconscious")
                    ch.death_saves_success = 0
                    ch.death_saves_failure = 0
                    pre_lines.append("💀 Ты упал без сознания — начинаются спасброски смерти.")

        # === POST-NARRATIVE mechanics (applied, summarised, shown after story) ===
        post_lines: list[str] = []

        if plan.direct_hp_change != 0:
            old, new = engine.apply_damage(ch, plan.direct_hp_change, damage_type="")
            post_lines.append(f"♥ HP: {old} → {new}")
            if ch.hp_current == 0 and plan.direct_hp_change < 0:
                _add_cond(ch, "unconscious")
                ch.death_saves_success = 0
                ch.death_saves_failure = 0
                post_lines.append("💀 Ты упал без сознания — начинаются спасброски смерти.")
            elif ch.hp_current > 0:
                _remove_cond(ch, "unconscious")

        if plan.inventory_changes:
            inv = json.loads(ch.inventory_json or "[]")
            for change in plan.inventory_changes:
                if change.action == "add":
                    new_item = {
                        "name": change.name,
                        "quantity": change.quantity,
                        "type": change.item_type or "misc",
                        "is_equipped": False,
                    }
                    if change.damage_dice:
                        new_item["damage_dice"] = change.damage_dice
                    if change.emoji:
                        new_item["emoji"] = change.emoji
                    inv.append(new_item)
                    dmg_tag = f" [урон {change.damage_dice}]" if change.damage_dice else ""
                    post_lines.append(
                        f"🎒 Добавлено: {change.emoji + ' ' if change.emoji else ''}{change.name} ×{change.quantity}{dmg_tag}"
                    )
                elif change.action in {"remove", "use"}:
                    for item in inv:
                        if item.get("name", "").lower() == change.name.lower():
                            item["quantity"] = max(0, int(item.get("quantity", 1)) - change.quantity)
                            post_lines.append(
                                f"🎒 Использовано: {change.name} ×{change.quantity}"
                            )
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
            post_lines.append(f"⭐ +{plan.xp_award} XP")
            while ch.xp_current >= ch.xp_to_next_level:
                ch.level += 1
                ch.xp_to_next_level += 300 + (ch.level - 1) * 200
                ch.hp_max += 6 + max(1, ch.ability_mod("CON"))
                ch.hp_current = ch.hp_max
                ch.proficiency_bonus = 2 + max(0, (ch.level - 1) // 4)
                post_lines.append(f"🎉 Новый уровень: {ch.level}")

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
            post_lines.append(f"📊 Репутация {rep.faction}: {old_rep} → {fr.reputation_score}")

        # Direct gold movement from trading, loot purses, tips.
        if plan.direct_gold_change:
            old_gold = ch.gold
            ch.gold = max(0, ch.gold + plan.direct_gold_change)
            sign = "+" if plan.direct_gold_change > 0 else ""
            post_lines.append(f"💰 Золото: {old_gold} → {ch.gold} ({sign}{plan.direct_gold_change})")

        # Trade offer from a merchant — persist NPC inventory + render pitch.
        if plan.trade_offer and plan.trade_offer.npc:
            await self._apply_trade_offer(db, user, plan.trade_offer)
            lines_for_offer = self._format_trade_offer(plan.trade_offer)
            post_lines.append(lines_for_offer)

        # Grant a recipe — append to known_recipes_json (dedup by name).
        if plan.grant_recipe and plan.grant_recipe.name:
            added = self._grant_recipe(ch, plan.grant_recipe)
            if added:
                post_lines.append(
                    f"📜 Получен рецепт: <b>{plan.grant_recipe.name}</b> — /craft чтобы скрафтить."
                )

        # Clean up dead enemies + close combat if the scene is empty.
        scene = [e for e in scene if int(e.get("hp_current", 0) or 0) > 0]
        if gs.combat_active and not scene:
            engine.end_combat(gs)
            post_lines.append("🏳 Все враги повержены — бой окончен.")
        elif gs.combat_active:
            # End of player's turn in combat → bump round, reset economy.
            engine.advance_round(gs, ch)
            post_lines.append(f"🔄 Раунд {gs.round_number} — действие готово снова.")
        gs.scene_state_json = json.dumps(scene, ensure_ascii=False)

        options = self._ensure_options(plan.options)
        gs.last_options_json = json.dumps(options, ensure_ascii=False)

        # Trigger an async adventure summary every N turns. This is a
        # background task — the player doesn't wait for it. If it fails we
        # swallow the error silently; the summary field just stays stale.
        if gs.turn_number and gs.turn_number % _SUMMARY_EVERY_N_TURNS == 0:
            import asyncio
            asyncio.create_task(self._refresh_adventure_summary(user.id))

        body = plan.narrative.strip() or "..."
        pre_block = "\n".join(pre_lines).strip()
        post_block = "\n".join(post_lines).strip()

        # Order: MECHANICS (pre) → NARRATIVE → AFTER-EFFECTS. User explicitly
        # asked to see rolls & damage BEFORE the story text.
        parts = [x for x in (pre_block, body, post_block) if x]
        text = "\n\n".join(parts)

        await self.save_message(db, user.id, "assistant", text)
        return TurnOutput(text=text, options=options)

    async def _handle_death_save_turn(
        self, db: AsyncSession, user: User, ch: Character, gs: GameSession,
    ) -> TurnOutput:
        """When the character is unconscious, the turn becomes a single death
        save — no LLM involvement, no inventory changes, no combat rolls.
        Match TZ: "При HP = 0 персонаж без сознания, каждый ход бросает 1d20".
        """
        result = engine.roll_death_save(ch)
        lines: list[str] = [result.format()]

        if result.woke_up:
            _remove_cond(ch, "unconscious")
            lines.append("✨ Ты приходишь в себя с 1 HP. Можешь действовать.")
            opts = self._ensure_options([
                "Подняться и оценить обстановку",
                "Лежать и восстановить дыхание",
                "Схватить первое попавшееся оружие",
                "Позвать на помощь",
            ])
        elif result.dead:
            _add_cond(ch, "dead")
            gs.combat_active = False
            gs.scene_state_json = "[]"
            lines.append("☠ <b>Персонаж мёртв.</b>")
            opts = ["🔄 Начать новую игру", "📋 Меню", "✏ Написать свой вариант"]
        elif result.stabilized:
            _add_cond(ch, "stabilized")
            lines.append("🩹 Ты стабилизирован. Без сознания, но не умираешь.")
            opts = [
                "Лежать и ждать помощи",
                "Попытаться очнуться через время",
                "✏ Написать свой вариант",
            ]
        else:
            lines.append("…Ты без сознания. На следующем ходу — очередной спасбросок.")
            opts = [
                "Продолжить (ещё спасбросок)",
                "Позвать на помощь (если рядом есть союзники)",
                "✏ Написать свой вариант",
            ]

        gs.last_options_json = json.dumps(opts, ensure_ascii=False)
        text = "\n".join(lines)
        await self.save_message(db, user.id, "assistant", text)
        return TurnOutput(text=text, options=opts)

    async def _refresh_adventure_summary(self, user_id: int) -> None:
        """Background task: condense recent play into gs.adventure_summary.

        Uses its own DB session because this runs AFTER the parent request
        has already committed — reusing the middleware session would race
        with the commit at the end of the handler.
        """
        try:
            from bot.db import SessionLocal
            async with SessionLocal() as db:
                user = await db.scalar(select(User).where(User.id == user_id))
                if not user:
                    return
                gs = await db.scalar(select(GameSession).where(GameSession.user_id == user_id))
                if not gs:
                    return
                msgs = await self.get_recent_messages(db, user_id, 20)
                if not msgs:
                    return
                transcript = "\n".join(
                    f"{m.role.upper()}: {m.content[:500]}" for m in msgs
                )
                try:
                    summary = await self.gemini.summarize_adventure(
                        prior=gs.adventure_summary or "",
                        transcript=transcript,
                    )
                except Exception:
                    log.exception("Adventure summary generation failed")
                    return
                if summary:
                    gs.adventure_summary = summary[:4000]
                    await db.commit()
        except Exception:
            log.exception("Adventure summary task failed")

    # ─── Trading ──────────────────────────────────────────────────────

    async def _apply_trade_offer(
        self, db: AsyncSession, user: User, offer: TradeOffer,
    ) -> NPCState:
        """Store (or update) the merchant's inventory in NPCState so /shop
        can show it even if the player types a new message and the offer
        leaves the visible chat log.
        """
        npc = await db.scalar(
            select(NPCState).where(
                NPCState.user_id == user.id, NPCState.name == offer.npc,
            )
        )
        gs = await db.scalar(select(GameSession).where(GameSession.user_id == user.id))
        items_json = json.dumps(
            [it.model_dump() for it in offer.items], ensure_ascii=False
        )
        if not npc:
            npc = NPCState(
                user_id=user.id,
                name=offer.npc,
                current_location=gs.current_location if gs else "",
                attitude="neutral",
                inventory_json=items_json,
                notes=f"buys_from_player={offer.buys_from_player}; rate={offer.buy_back_rate}",
            )
            db.add(npc)
            await db.flush()
        else:
            npc.inventory_json = items_json
            if gs:
                npc.current_location = gs.current_location
            npc.notes = f"buys_from_player={offer.buys_from_player}; rate={offer.buy_back_rate}"
        return npc

    @staticmethod
    def _format_trade_offer(offer: TradeOffer) -> str:
        if not offer.items:
            return f"🛒 <b>{offer.npc}</b>: сейчас у торговца пусто."
        lines = [f"🛒 <b>{offer.npc}</b> предлагает:"]
        for it in offer.items:
            emoji = it.emoji or "•"
            dmg = f" [{it.damage_dice}]" if it.damage_dice else ""
            qty = f" ×{it.quantity}" if it.quantity > 1 else ""
            lines.append(f" • {emoji} {it.name}{dmg}{qty} — 💰 {it.price}")
        if offer.buys_from_player:
            rate = int(offer.buy_back_rate * 100)
            lines.append(f"\n<i>Скупает б/у по {rate}% номинала. /sell &lt;предмет&gt; чтобы продать.</i>")
        lines.append("<i>/buy &lt;предмет&gt; чтобы купить.</i>")
        return "\n".join(lines)

    async def find_active_merchant(
        self, db: AsyncSession, user: User,
    ) -> NPCState | None:
        """Return the merchant NPC standing in the player's current location
        (whose inventory_json isn't empty). Prefers the most recently touched
        one when several are present.
        """
        gs = await self.ensure_session(db, user)
        npcs = list(await db.scalars(
            select(NPCState).where(NPCState.user_id == user.id)
        ))
        for n in npcs:
            if n.current_location != gs.current_location:
                continue
            try:
                items = json.loads(n.inventory_json or "[]")
            except Exception:
                items = []
            if items:
                return n
        return None

    @staticmethod
    def format_shop(npc: NPCState | None) -> str:
        if not npc:
            return (
                "🛒 Торговцев рядом нет. Подойди к NPC с товаром или попроси "
                "GM представить тебе торговца."
            )
        try:
            items = json.loads(npc.inventory_json or "[]")
        except Exception:
            items = []
        if not items:
            return f"🛒 <b>{npc.name}</b>: сейчас у торговца пусто."
        lines = [f"🛒 <b>{npc.name}</b> — прилавок:"]
        for it in items:
            emoji = it.get("emoji") or "•"
            dmg = f" [{it.get('damage_dice')}]" if it.get("damage_dice") else ""
            qty = f" ×{it.get('quantity', 1)}" if int(it.get("quantity", 1) or 1) > 1 else ""
            lines.append(f" • {emoji} {it.get('name')}{dmg}{qty} — 💰 {it.get('price', '?')}")
        lines.append("\n<i>/buy &lt;название&gt; — купить, /sell &lt;название&gt; — продать.</i>")
        return "\n".join(lines)

    async def perform_buy(
        self, db: AsyncSession, user: User, item_name: str, quantity: int = 1,
    ) -> str:
        """Buy `quantity` of `item_name` from the current location's merchant.

        Rules:
          - Merchant must exist at current location with matching item.
          - Character must have enough gold.
          - Item is decremented from NPC inventory, stacked into PC inventory,
            gold moves, and a human-readable line is returned.
        """
        ch = await self.ensure_character(db, user)
        npc = await self.find_active_merchant(db, user)
        if not npc:
            return "🛒 Торговцев рядом нет — покупать не у кого."
        try:
            items = json.loads(npc.inventory_json or "[]")
        except Exception:
            items = []
        low = (item_name or "").strip().lower()
        idx = next(
            (i for i, it in enumerate(items)
             if low in (it.get("name") or "").lower()
             or (it.get("name") or "").lower() in low),
            None,
        )
        if idx is None:
            return f"🛒 У {npc.name} нет «{item_name}»."
        entry = items[idx]
        available = int(entry.get("quantity", 1) or 1)
        want = max(1, min(quantity, available))
        price = int(entry.get("price", 0) or 0) * want
        if ch.gold < price:
            return f"💰 Не хватает золота: нужно {price}, есть {ch.gold}."

        ch.gold -= price
        new_item = {
            "name": entry.get("name", ""),
            "emoji": entry.get("emoji", "•"),
            "type": entry.get("item_type", "misc"),
            "quantity": want,
            "is_equipped": False,
        }
        if entry.get("damage_dice"):
            new_item["damage_dice"] = entry["damage_dice"]

        pc_inv = json.loads(ch.inventory_json or "[]")
        existing = next(
            (i for i, it in enumerate(pc_inv)
             if (it.get("name") or "").lower() == new_item["name"].lower()
             and it.get("type") == new_item["type"]),
            None,
        )
        if existing is not None:
            pc_inv[existing]["quantity"] = int(pc_inv[existing].get("quantity", 1) or 1) + want
        else:
            pc_inv.append(new_item)
        ch.inventory_json = json.dumps(pc_inv, ensure_ascii=False)

        entry["quantity"] = available - want
        if entry["quantity"] <= 0:
            items.pop(idx)
        npc.inventory_json = json.dumps(items, ensure_ascii=False)

        return (
            f"🛒 Куплено: {new_item.get('emoji', '•')} {new_item['name']} ×{want} — "
            f"−{price} 💰 (осталось {ch.gold})."
        )

    async def perform_sell(
        self, db: AsyncSession, user: User, item_name: str, quantity: int = 1,
    ) -> str:
        """Sell `quantity` of `item_name` from PC inventory to the current
        merchant. Price = NPC's listed price × buy_back_rate (default 50%).
        Falls back to 10 gold for items that have no known market price.
        """
        ch = await self.ensure_character(db, user)
        npc = await self.find_active_merchant(db, user)
        if not npc:
            return "🛒 Торговцев рядом нет — продавать некому."
        pc_inv = json.loads(ch.inventory_json or "[]")
        low = (item_name or "").strip().lower()
        idx = next(
            (i for i, it in enumerate(pc_inv)
             if low in (it.get("name") or "").lower()
             or (it.get("name") or "").lower() in low),
            None,
        )
        if idx is None:
            return f"🎒 В инвентаре нет «{item_name}»."
        entry = pc_inv[idx]
        available = int(entry.get("quantity", 1) or 1)
        want = max(1, min(quantity, available))

        try:
            npc_items = json.loads(npc.inventory_json or "[]")
        except Exception:
            npc_items = []
        base_price = 10
        rate = 0.5
        notes = (npc.notes or "")
        m = re.search(r"rate=([0-9.]+)", notes)
        if m:
            try:
                rate = float(m.group(1))
            except Exception:
                pass
        matching_offer = next(
            (it for it in npc_items
             if (it.get("name") or "").lower() == (entry.get("name") or "").lower()),
            None,
        )
        if matching_offer:
            base_price = int(matching_offer.get("price", base_price) or base_price)
        price = max(1, int(base_price * rate)) * want
        ch.gold += price

        entry["quantity"] = available - want
        if entry["quantity"] <= 0:
            pc_inv.pop(idx)
        ch.inventory_json = json.dumps(pc_inv, ensure_ascii=False)

        return (
            f"🛒 Продано: {entry.get('emoji', '•')} {entry.get('name')} ×{want} — "
            f"+{price} 💰 (итого {ch.gold})."
        )

    # ─── Crafting ─────────────────────────────────────────────────────

    @staticmethod
    def _grant_recipe(ch: Character, recipe: Recipe) -> bool:
        """Append a recipe to `known_recipes_json` if not already there.
        Returns True if it was actually added."""
        try:
            recipes = json.loads(ch.known_recipes_json or "[]")
        except Exception:
            recipes = []
        key = recipe.name.strip().lower()
        for r in recipes:
            if (r.get("name") or "").strip().lower() == key:
                return False
        recipes.append(recipe.model_dump())
        ch.known_recipes_json = json.dumps(recipes, ensure_ascii=False)
        return True

    @staticmethod
    def format_recipes(ch: Character) -> str:
        try:
            recipes = json.loads(ch.known_recipes_json or "[]")
        except Exception:
            recipes = []
        if not recipes:
            return (
                "📜 Рецептов пока нет. Находи чертежи, учись у мастеров — "
                "LLM сможет вручить /craft-рецепты по сюжету."
            )
        lines = ["📜 <b>Известные рецепты</b>"]
        for r in recipes:
            comps = ", ".join(
                f"{c.get('name')}×{c.get('quantity', 1)}"
                for c in r.get("components", [])
            ) or "—"
            lines.append(
                f" • <b>{r.get('name')}</b> → {r.get('result_emoji', '•')} "
                f"{r.get('result_name', r.get('name'))} "
                f"(DC {r.get('dc', 12)} {r.get('skill', 'ловкость рук')}) — "
                f"нужно: {comps}"
            )
        lines.append("\n<i>/craft &lt;название&gt; чтобы попробовать.</i>")
        return "\n".join(lines)

    async def craft_item(
        self, db: AsyncSession, user: User, recipe_name: str,
    ) -> str:
        """Run one crafting attempt. Returns a chat-ready summary string."""
        ch = await self.ensure_character(db, user)
        gs = await self.ensure_session(db, user)
        try:
            recipes = json.loads(ch.known_recipes_json or "[]")
        except Exception:
            recipes = []
        low = (recipe_name or "").strip().lower()
        target = next(
            (r for r in recipes
             if low == (r.get("name") or "").strip().lower()
             or low in (r.get("name") or "").lower()),
            None,
        )
        if target is None:
            return f"📜 Рецепт «{recipe_name}» не найден. Посмотри список — /craft без аргумента."

        result = engine.attempt_craft(ch, target, gs=gs)

        if result.missing:
            return (
                f"❌ Не хватает компонентов для «{target.get('name')}»:\n"
                + "\n".join(f" • {m}" for m in result.missing)
            )

        lines: list[str] = [result.roll_line]
        spent = ", ".join(
            f"{name}×{qty}" for name, qty in result.components_consumed
        ) or "—"
        lines.append(f"🧰 Потрачено: {spent}")
        if result.success:
            lines.append(
                f"✅ Изготовлено: {target.get('result_emoji', '•')} "
                f"{result.produced_name} ×{result.produced_quantity}"
            )
        else:
            lines.append("💥 Провал: компоненты частично испорчены.")
        return "\n".join(lines)

    async def perform_rest(
        self, db: AsyncSession, user: User, kind: str,
    ) -> TurnOutput:
        """Run a short or long rest through the engine. Returns chat output.

        kind: "short" | "long". Blocks long rest during combat.
        """
        ch = await self.ensure_character(db, user)
        gs = await self.ensure_session(db, user)

        if kind == "long" and gs.combat_active:
            return TurnOutput(
                text="⚠ Длинный отдых невозможен в бою. Сначала заверши стычку.",
                options=self._ensure_options(json.loads(gs.last_options_json or "[]")),
            )

        if kind == "short":
            lines = engine.perform_short_rest(ch)
        else:
            lines = engine.perform_long_rest(ch)

        text = "\n".join(lines)
        options = self._ensure_options(json.loads(gs.last_options_json or "[]"))
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
