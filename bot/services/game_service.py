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
    Ability,
    AbilityUse,
    CharacterSetup,
    CompanionSpec,
    EnemyAction,
    InventoryChange,
    LevelUpOffer,
    LevelUpPerk,
    QuestEvent,
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
_SUMMARY_EVERY_N_TURNS = 5

# How many turns must pass between two `quest_events.create` events before
# we accept a new quest row. Stops the LLM from spamming the journal with
# variations on the same theme ("Найти сестру" → "По следам сестры" →
# "След крови" — all the same arc).
_QUEST_CREATE_COOLDOWN_TURNS = 5

# How many turns of inactivity before an active quest is auto-archived to
# "stale" status. Keeps /quests scannable.
_QUEST_STALE_TURNS = 20


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
    weight = float(it.get("weight_kg", 0) or 0)
    needs_att = bool(it.get("requires_attunement"))

    parts = [f"{emoji} {name}"]
    if qty > 1:
        parts.append(f"×{qty}")
    if dmg:
        parts.append(f"[урон {dmg}]")
    if not short:
        if weight:
            parts.append(f"[{weight:g} кг]")
        if needs_att:
            parts.append("✨")
        if equipped:
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
                if it.weight_kg:
                    item["weight_kg"] = float(it.weight_kg)
                if it.requires_attunement:
                    item["requires_attunement"] = True
                inv.append(item)
                if it.is_equipped:
                    slot = it.item_type or "misc"
                    equip[slot] = {"name": it.name, "emoji": it.emoji or "•"}
            ch.inventory_json = json.dumps(inv, ensure_ascii=False)
            if equip:
                ch.equipment_json = json.dumps(equip, ensure_ascii=False)
        if setup.starting_abilities:
            starter_powers: list[dict] = []
            for ab in setup.starting_abilities:
                power = ab.model_dump()
                if int(power.get("current_uses", 0) or 0) == 0:
                    power["current_uses"] = int(power.get("max_uses", 1) or 1)
                starter_powers.append(power)
            ch.powers_json = json.dumps(starter_powers, ensure_ascii=False)
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

        # Replay onboarding preferences + personal stake into EVERY prompt.
        prefs_line = ""
        stake_line = ""
        try:
            onb = json.loads(gs.onboarding_state_json or "{}")
        except Exception:
            onb = {}
        if isinstance(onb, dict):
            bits = []
            if onb.get("tone"):
                bits.append(f"Тон: {onb['tone']}")
            if onb.get("rating"):
                rating = onb["rating"]
                hint = {
                    "13": "детям OK, без графического насилия и секса",
                    "16": "кровь, мрачные темы, мат уместен",
                    "18": "без цензуры — секс, мат, жесть допустимы если уместно",
                }.get(str(rating), "")
                bits.append(f"Рейтинг: {rating}+ ({hint})" if hint else f"Рейтинг: {rating}+")
            if onb.get("pace"):
                pace_hint = {
                    "Быстрый": "короткие описания, экшен в каждом ходе",
                    "Средний": "баланс между атмосферой и темпом",
                    "Медленный": "длинные сцены, сенсорные детали, паузы",
                }
                pace = onb["pace"].replace("🚀 ", "").replace("⚖ ", "").replace("📜 ", "")
                bits.append(f"Темп: {pace} ({pace_hint.get(pace, '')})")
            if onb.get("difficulty"):
                diff_hint = {
                    "Лайт": "ГМ помогает игроку, прощает ошибки, смерть = откат",
                    "Норма": "честные правила, броски решают",
                    "Хардкор": "жёстко, без подсказок, любая ошибка может стоить персонажа",
                }
                diff = onb["difficulty"].replace("🌱 ", "").replace("⚖ ", "").replace("💀 ", "")
                bits.append(f"Сложность: {diff} ({diff_hint.get(diff, '')})")
            if bits:
                prefs_line = "PlayerPreferences (соблюдай в каждом ходе): " + " | ".join(bits) + "\n"
            stake = (onb.get("stake") or "").strip()
            if stake:
                stake_line = (
                    f"Личная ставка (что/кого игрок боится потерять): {stake}\n"
                    f"  Привязывай к этой ставке каждый 3-й значимый поворот: "
                    f"NPC напоминают о ней, локации дают намёки, квесты дают угрозу.\n"
                )

        # Recent NPCs — last 8 named NPCs sorted by recency. Without this
        # block the LLM forgets characters as soon as their mention scrolls
        # out of the 20-message window. Forces callbacks.
        npcs = list(await db.scalars(
            select(NPCState)
            .where(NPCState.user_id == user.id, NPCState.is_companion == False)  # noqa: E712
            .order_by(desc(NPCState.last_seen_turn), desc(NPCState.id))
            .limit(8)
        ))
        npc_line = ""
        if npcs:
            npc_line = (
                "Recent NPCs (реферни хотя бы одного раз в 3-5 ходов когда уместно — "
                "используй их голос, долги, обещания, секреты как сюжетные крючки):\n"
            )
            for n in npcs:
                dead_tag = " †" if (n.attitude == "dead" or (n.death_turn or 0) > 0) else ""
                header_bits = [n.name + dead_tag]
                if n.role:
                    header_bits.append(n.role)
                if n.faction:
                    header_bits.append(f"фракция: {n.faction}")
                meta = ", ".join(header_bits[1:])
                bond = int(n.bond or 0)
                bond_str = f", связь {bond:+d}" if bond else ""
                npc_line += f"  • {header_bits[0]}"
                if meta:
                    npc_line += f" ({meta})"
                npc_line += f"{bond_str}, last_seen turn {n.last_seen_turn}\n"
                if n.appearance:
                    npc_line += f"    внешность: {n.appearance[:200]}\n"
                if n.speech_style:
                    npc_line += f"    голос: {n.speech_style[:120]}\n"
                if n.last_quote:
                    npc_line += f"    последняя реплика: «{n.last_quote[:180]}»\n"
                for lbl, raw in (
                    ("обещания", n.promises_json),
                    ("долги", n.debts_json),
                    ("знает секрет", n.secrets_known_json),
                    ("получил подарок", n.gifts_received_json),
                ):
                    try:
                        items = json.loads(raw or "[]")
                    except Exception:
                        items = []
                    if items:
                        npc_line += f"    {lbl}: {'; '.join(str(x)[:120] for x in items[-3:])}\n"
                if n.death_turn:
                    cause = f" ({n.death_cause})" if n.death_cause else ""
                    npc_line += f"    † умер на ходу {n.death_turn}{cause} — призрак/память может всплыть\n"

        # Active quests — title + remaining deadline so the LLM can weave
        # time pressure into the narrative.
        quests = list(await db.scalars(
            select(Quest).where(
                Quest.user_id == user.id, Quest.status == "active",
            ).limit(8)
        ))
        quest_line = ""
        if quests:
            quest_line = "Active Quests (используй update/complete_step вместо нового create если похожий есть):\n"
            for q in quests:
                d = int(q.deadline_turns_remaining or 0)
                clock = f" ⏳{d}" if d > 0 else ""
                tag = "⭐" if q.is_main else "·"
                quest_line += f"  {tag} {q.title}{clock}\n"

        beat_line = f"Current Beat (атомарная цель сейчас): {gs.current_beat}\n" if gs.current_beat else ""
        summary_line = f"Adventure Summary: {gs.adventure_summary}\n" if gs.adventure_summary else ""

        return (
            f"Player: {ch.name} ({ch.race} {ch.char_class}, level {ch.level})\n"
            f"HP: {ch.hp_current}/{ch.hp_max} temp:{ch.temp_hp} AC:{ch.ac} gold:{ch.gold}\n"
            f"Abilities: {abilities}\n"
            f"Skills: {json.loads(ch.skill_proficiencies_json or '[]')}\n"
            f"Conditions: {json.loads(ch.conditions_json or '[]')}\n"
            f"Location: {gs.current_location}\n"
            f"Location Description: {gs.current_location_description}\n"
            f"{summary_line}"
            f"{beat_line}"
            f"{quest_line}"
            f"{npc_line}"
            f"Universe: {gs.universe}; Style: {gs.narrative_style}; Weather:{gs.weather}; Time:{gs.time_of_day}\n"
            f"{prefs_line}"
            f"{stake_line}"
            f"Recent Messages:\n{recent}"
        )

    @staticmethod
    def _ensure_options(options: list[str]) -> list[str]:
        # Strip LLM-added numbering ("1. Открыть", "2) Уйти", "- Бежать") —
        # buttons already display 1-5, double-numbering is visual noise.
        prefix_re = re.compile(r"^\s*(?:\d{1,2}[.\)]\s*|[-•·]\s*)")
        clean = []
        for o in options or []:
            if not o or not o.strip():
                continue
            clean.append(prefix_re.sub("", o).strip())
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
    def format_starter_screen(ch: Character) -> str:
        """Rich starter card shown ONCE right after onboarding — gives the
        new player a 5-second scan of who they are and what they can do.
        Uses Russian stat names (NOT STR/DEX/...) per UX brief: target audience
        has never seen a D&D character sheet.
        """
        ABILITY_FULL_RU = {
            "STR": ("💪 Сила",         "урон в ближнем бою, ношение тяжестей"),
            "DEX": ("🤸 Ловкость",     "точность, уворот, скрытность"),
            "CON": ("🛡 Телосложение", "ХП и стойкость"),
            "INT": ("🧠 Интеллект",    "знания, расследование, магия"),
            "WIS": ("👁 Мудрость",     "внимание, выживание, восприятие"),
            "CHA": ("😎 Харизма",      "убеждение, обман, выступление"),
        }
        REFRESH_RU = {
            "short": "восст. за короткий отдых",
            "long": "восст. за длинный отдых",
            "encounter": "восст. после боя",
            "at_will": "без ограничений",
        }

        try:
            abilities = json.loads(ch.abilities_json or "{}")
        except Exception:
            abilities = {}
        try:
            inv = json.loads(ch.inventory_json or "[]")
        except Exception:
            inv = []
        try:
            powers = json.loads(ch.powers_json or "[]")
        except Exception:
            powers = []

        head = f"═══ ТВОЙ ПЕРСОНАЖ ═══\n<b>{ch.name}</b>"
        tail = " ".join(x for x in (ch.race, ch.char_class) if x)
        if tail:
            head += f", {tail}"
        head += f", {ch.level} ур.\n"
        head += f"❤ HP {ch.hp_current}/{ch.hp_max}   🛡 КД {ch.ac}   ⚡ Скорость {ch.speed_m}м"

        stats_lines = ["", "═══ ХАРАКТЕРИСТИКИ ═══"]
        for key in ("STR", "DEX", "CON", "INT", "WIS", "CHA"):
            score = int(abilities.get(key, 10) or 10)
            mod = (score - 10) // 2
            label, blurb = ABILITY_FULL_RU.get(key, (key, ""))
            stats_lines.append(f"{label} {score} ({mod:+d}) — <i>{blurb}</i>")

        sections: list[str] = [head, "\n".join(stats_lines)]

        if powers:
            ab_lines = ["═══ ЧТО ТЫ УМЕЕШЬ ═══"]
            for p in powers:
                emoji = p.get("emoji") or "✨"
                name = p.get("name", "?")
                refresh = (p.get("refresh") or "long").lower()
                cur = int(p.get("current_uses", 0) or 0)
                mx = int(p.get("max_uses", 1) or 1)
                if refresh == "at_will":
                    charges = "без ограничений"
                else:
                    charges = f"{cur}/{mx} ({REFRESH_RU.get(refresh, refresh)})"
                ab_lines.append(f"{emoji} <b>{name}</b> — {charges}")
                if p.get("description"):
                    ab_lines.append(f"  <i>— {p['description']}</i>")
            sections.append("\n".join(ab_lines))

        if inv:
            inv_lines = ["═══ В РЮКЗАКЕ ═══"]
            for it in inv:
                inv_lines.append(_format_inventory_item(it, short=False))
            inv_lines.append(f"💰 Золото: {ch.gold}")
            sections.append("\n".join(inv_lines))

        hints = (
            "═══ КАК ИГРАТЬ ═══\n"
            "• Жми кнопки 1–5 — быстрый выбор готового варианта\n"
            "• Или просто <b>пиши действия словами</b> — ГМ поймёт\n"
            "• <code>ГМ: вопрос</code> — задать вопрос правил\n"
            "• 📋 Меню — карточка, инвентарь, способности, отдых"
        )
        sections.append(hints)

        return "\n\n".join(sections)

    @staticmethod
    def format_inventory_detailed(ch: Character) -> str:
        inv = json.loads(ch.inventory_json or "[]")
        if not inv:
            return "🎒 <b>Инвентарь пуст.</b>"

        # Group by type. Order: weapons / armor / consumables / quest / misc.
        # By 10-15 turns the inventory grows to 8+ items and a flat list
        # becomes hard to scan during a combat scene.
        order = [
            ("weapon",     "⚔ <b>Оружие ближнего боя</b>"),
            ("ranged",     "🏹 <b>Оружие дальнего боя</b>"),
            ("armor",      "🛡 <b>Броня и одежда</b>"),
            ("consumable", "🧪 <b>Расходники</b>"),
            ("quest",      "🎗 <b>Квестовые предметы</b>"),
            ("misc",       "🎒 <b>Прочее</b>"),
        ]
        bucket: dict[str, list[dict]] = {k: [] for k, _ in order}
        for it in inv:
            t = (it.get("type") or "misc").lower()
            if t not in bucket:
                t = "misc"
            bucket[t].append(it)

        lines: list[str] = ["🎒 <b>Инвентарь</b>"]
        for key, title in order:
            items = bucket[key]
            if not items:
                continue
            lines.append("")
            lines.append(title)
            for it in items:
                lines.append(" • " + _format_inventory_item(it, short=False))
        lines.append(f"\n💰 <b>Золото:</b> {ch.gold}")
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

        # Seed beat-line from the opening — if the LLM didn't fill it,
        # fall back to the quest-hook so the player isn't staring at an
        # empty "🎯 Сейчас:" slot on turn 1.
        if plan.current_beat:
            gs.current_beat = plan.current_beat[:120]
        elif plan.quest_update:
            gs.current_beat = plan.quest_update[:120]

        # Persist named NPCs introduced in the opening scene so they exist
        # in the registry from turn 1 — without this the GM can introduce
        # a fiancée / boss / mentor in the intro and forget them by turn 4.
        for npc_app in plan.npc_appearances or []:
            await self._upsert_npc_appearance(db, user, gs, npc_app)

        # Use the rich starter screen (UX brief #1) instead of the cramped
        # one-liner intro — new players need to see who they are, what they
        # carry, what they can do, and how to play. ALL Russian, no DEX/STR.
        starter = self.format_starter_screen(ch)
        beat_line = f"\n\n🎯 <b>Сейчас:</b> {gs.current_beat}" if gs.current_beat else ""
        full_text = f"{starter}\n\n━━━━━━━━━━━━━━━━━━\n\n{narrative}{beat_line}"
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
        # Tracked across roll resolution — set True if ANY roll the LLM
        # asked for failed. Used after-the-fact to strip xp/items/abilities
        # off the same-turn reward suite (fail-is-fail rule).
        had_failed_roll = False

        if gs.combat_active and scene:
            if combat_started_now:
                pre_lines.append("⚔ Начинается бой! Инициатива брошена.")
            pre_lines.append(engine.format_combat_status(gs))
            enemies_line = " | ".join(
                f"{e.get('name', '?')} (HP {e.get('hp_current', '?')}/{e.get('hp_max', '?')}, КД {e.get('ac', '?')})"
                for e in scene
            )
            pre_lines.append(f"⚔ Враги на сцене: {enemies_line}")

        # Passive perception auto-check (no d20). Only surfaced on SUCCESS —
        # failed PP silently does nothing. The old behavior leaked DC + the
        # word "не замечено" in nearly every message, which read as constant
        # mechanical noise without giving the player anything actionable.
        if plan.passive_perception_dc and plan.passive_perception_dc > 0:
            pp = engine.passive_perception(ch)
            if pp >= plan.passive_perception_dc and plan.passive_perception_reveal:
                pre_lines.append(f"👁 <i>{plan.passive_perception_reveal}</i>")

        for rr in plan.rolls:
            if rr.type == "skill":
                rep_score = None
                if rr.faction:
                    fr = await db.scalar(
                        select(FactionReputation).where(
                            FactionReputation.user_id == user.id,
                            FactionReputation.faction_name == rr.faction,
                        )
                    )
                    rep_score = fr.reputation_score if fr else 0
                rich = engine.make_skill_check(
                    ch, rr.label, rr.dc,
                    advantage=rr.advantage, disadvantage=rr.disadvantage,
                    gs=gs,
                    reputation_score=rep_score,
                )
                # Pre-roll preview — show the formula + chance BEFORE the
                # d20 resolves. Lets the player feel the stakes ("60% шанс
                # успеха") instead of finding out the DC after the fact.
                pre_lines.append(engine.preview_skill_check(ch, rr.label, rr.dc))
                # Skill checks default to a one-liner — full breakdown only
                # on crit/fumble (auto-promoted by RichRoll.format).
                pre_lines.append(rich.format(kind="Проверка"))
                if not rich.success:
                    had_failed_roll = True
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

                if not dmg_expr:
                    pre_lines.append(
                        f"⚠ Атака «{rr.label}»: нет подходящего оружия в руках — бросок не делаем."
                    )
                    continue

                if gs.combat_active and gs.action_used:
                    pre_lines.append(
                        f"⚠ Атака «{rr.label}»: действие уже потрачено в этом раунде."
                    )
                    continue
                if gs.combat_active:
                    gs.action_used = True

                # Pre-roll preview — let the player see what's about to be
                # thrown BEFORE the result lands (UX brief #3). One compact
                # block, not a separate message.
                target_idx_preview = _find_scene_target(scene, rr.target)
                target_name_for_preview = ""
                target_ac_for_preview = rr.dc
                if target_idx_preview is not None:
                    tgt = scene[target_idx_preview]
                    target_name_for_preview = tgt.get("name", "Враг")
                    target_ac_for_preview = int(tgt.get("ac", rr.dc) or rr.dc)
                    pre_lines.append(
                        f"🎯 <b>Прицеливаюсь:</b> {tgt.get('name', 'Враг')} "
                        f"(🛡 КД {tgt.get('ac', '?')}, ♥ {tgt.get('hp_current', '?')}/{tgt.get('hp_max', '?')})"
                    )
                pre_lines.append(engine.preview_attack(
                    ch, target_ac_for_preview, ability_key=ability_key,
                    label=rr.label or "атака", target_name=target_name_for_preview,
                ))

                rich = engine.make_attack_roll(
                    ch, rr.dc, ability_key=ability_key,
                    advantage=rr.advantage, disadvantage=rr.disadvantage,
                    label=rr.label or "атака",
                    gs=gs,
                )
                pre_lines.append(rich.format(kind="Атака"))
                if not rich.success:
                    had_failed_roll = True

                if rich.success and dmg_expr:
                    chosen_d20 = rich.d20 if rich.d20_alt is None else (
                        max(rich.d20, rich.d20_alt) if rich.advantage else min(rich.d20, rich.d20_alt)
                    )
                    crit = chosen_d20 == 20
                    dmg = engine.roll_damage_pretty(
                        dmg_expr, ability_mod_value=ab_mod_for_dmg, critical=crit,
                    )
                    ability_full = engine.ABILITY_RU.get(ability_key, ability_key)
                    pre_lines.append(engine.format_damage_breakdown(
                        dmg_expr, dmg.rolls, dmg.flat_mod, dmg.total,
                        critical=crit, damage_type=rr.damage_type or "",
                        ability_label=ability_full if not dmg.has_explicit_mod else "",
                    ))

                    target_idx = _find_scene_target(scene, rr.target)
                    if target_idx is not None:
                        entry = scene[target_idx]
                        hp_before = int(entry.get("hp_current", 0) or 0)
                        hp_after = max(0, hp_before - dmg.total)
                        entry["hp_current"] = hp_after
                        hp_max = int(entry.get("hp_max", hp_before) or hp_before)
                        bar = engine.hp_bar(hp_after, hp_max)
                        pre_lines.append(
                            f"♥ <b>{entry.get('name', 'Враг')}</b>: "
                            f"{hp_before} → {hp_after} HP ({-dmg.total:+d})\n"
                            f"   {bar}"
                        )
                        if hp_after == 0:
                            pre_lines.append(f"☠ <b>{entry.get('name', 'Враг')} повержен!</b>")
            elif rr.type == "save":
                pre_lines.append(engine.preview_save(ch, rr.ability or "CON", rr.dc))
                rich = engine.make_save_roll(
                    ch, rr.ability or "CON", rr.dc,
                    advantage=rr.advantage, disadvantage=rr.disadvantage,
                    gs=gs,
                )
                # Death-save-style rolls always get the full breakdown; for
                # everything else the one-liner is enough. Saves are rarely
                # numerous in a turn, so verbose stays readable.
                pre_lines.append(rich.format(kind="Спасбросок", verbose=True))
                if not rich.success:
                    had_failed_roll = True

        for ea in plan.enemy_actions:
            atk_d20 = random.randint(1, 20)
            atk_total = atk_d20 + ea.attack_bonus
            hit = atk_total >= ch.ac
            # Multi-line block mirroring the player's own attack format so
            # the chat reads consistently. The player should be able to
            # SEE that "the orc rolled a 17 because it needed 13 vs my AC".
            crit_tag = ""
            verdict_word = "Попадание"
            verdict_icon = "✅"
            if atk_d20 == 20:
                crit_tag = "💥 КРИТ! "
                verdict_word = "КРИТИЧЕСКОЕ ПОПАДАНИЕ"
                verdict_icon = "💥"
            elif atk_d20 == 1:
                crit_tag = "💀 ФУМБЛ! "
                verdict_word = "КРИТИЧЕСКИЙ ПРОМАХ"
                verdict_icon = "💀"
                hit = False
            elif not hit:
                verdict_word = "Промах"
                verdict_icon = "❌"
            margin = atk_total - ch.ac
            if hit:
                margin_str = f" (на {abs(margin)} больше)" if margin >= 0 else ""
            else:
                margin_str = f" (не хватило {abs(margin) + 1})" if crit_tag == "" else ""
            ea_block = [
                f"⚔ <b>{crit_tag}{ea.name} атакует тебя</b>" + (f" — <i>{ea.reason}</i>" if ea.reason else ""),
                f"┌ d20: <b>{atk_d20}</b>",
                f"├ Бонус: <b>{ea.attack_bonus:+d}</b>",
                f"└ Итого: <b>{atk_total}</b> vs твоя КД {ch.ac} → {verdict_icon} <b>{verdict_word}</b>{margin_str}",
            ]
            pre_lines.append("\n".join(ea_block))

            if hit and ea.damage_dice:
                dmg = engine.roll_damage_pretty(ea.damage_dice)
                old, new = engine.apply_damage(ch, -dmg.total, damage_type=ea.damage_type or "")
                applied = old - new
                type_str = engine.format_damage_type(ea.damage_type or "")
                head = f"💥 <b>Урон по тебе: {ea.damage_dice}</b>"
                if type_str:
                    head += f" {type_str}"
                lines = [head]
                rolls_str = ",".join(str(r) for r in dmg.rolls) if dmg.rolls else "—"
                lines.append(f"┌ Кости: [{rolls_str}] = <b>{sum(dmg.rolls) if dmg.rolls else dmg.total}</b>")
                if dmg.flat_mod:
                    lines.append(f"├ Модификатор: <b>{dmg.flat_mod:+d}</b>")
                if applied != dmg.total:
                    delta_word = "уменьшено сопротивлением" if applied < dmg.total else "увеличено уязвимостью"
                    lines.append(f"├ <i>{delta_word}: {dmg.total} → {applied}</i>")
                lines.append(f"└ Итого по HP: <b>−{applied}</b>")
                pre_lines.append("\n".join(lines))
                pre_lines.append(
                    f"♥ <b>Твои HP:</b> {old} → {new} HP\n"
                    f"   {engine.hp_bar(new, ch.hp_max)}"
                )
                if ch.hp_current == 0:
                    _add_cond(ch, "unconscious")
                    ch.death_saves_success = 0
                    ch.death_saves_failure = 0
                    pre_lines.append("💀 <b>Ты упал без сознания</b> — начинаются спасброски смерти.")

        # === POST-NARRATIVE mechanics (applied, summarised, shown after story) ===
        post_lines: list[str] = []

        # Fail-is-fail enforcement (system_prompt rule #1). If any roll the
        # LLM asked for failed this turn, strip same-turn rewards out of the
        # plan: no XP, no new items, no granted recipes/abilities, no quest
        # completions. Negative consequences (HP damage, lost gold, removed
        # items) stay — that's the whole point of failure.
        if had_failed_roll:
            stripped: list[str] = []
            if plan.xp_award > 0:
                stripped.append(f"XP×{plan.xp_award}")
                plan.xp_award = 0
            if plan.inventory_changes:
                kept = [c for c in plan.inventory_changes if c.action != "add"]
                if len(kept) < len(plan.inventory_changes):
                    stripped.append("новые предметы")
                plan.inventory_changes = kept
            if plan.grant_recipe:
                stripped.append(f"рецепт {plan.grant_recipe.name}")
                plan.grant_recipe = None
            if plan.grant_ability:
                stripped.append(f"способность {plan.grant_ability.name}")
                plan.grant_ability = None
            if plan.quest_events:
                kept_q = [q for q in plan.quest_events
                          if q.action not in ("complete", "complete_step")]
                if len(kept_q) < len(plan.quest_events):
                    stripped.append("завершение квеста")
                plan.quest_events = kept_q
            if stripped:
                log.info("Fail-is-fail: stripped %s due to failed roll", stripped)

        if plan.direct_hp_change != 0:
            old, new = engine.apply_damage(ch, plan.direct_hp_change, damage_type="")
            sign = "+" if plan.direct_hp_change > 0 else ""
            verb = "Лечение" if plan.direct_hp_change > 0 else "Урон"
            icon = "💚" if plan.direct_hp_change > 0 else "💥"
            post_lines.append(
                f"{icon} <b>{verb}:</b> {old} → {new} HP ({sign}{plan.direct_hp_change})\n"
                f"   {engine.hp_bar(new, ch.hp_max)}"
            )
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
                    if change.weight_kg:
                        new_item["weight_kg"] = float(change.weight_kg)
                    if change.requires_attunement:
                        new_item["requires_attunement"] = True
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
                # Baseline bumps — applied immediately so combat stays alive.
                ch.hp_max += 6 + max(1, ch.ability_mod("CON"))
                ch.hp_current = ch.hp_max
                ch.proficiency_bonus = 2 + max(0, (ch.level - 1) // 4)
                # Hit dice also grow with level.
                ch.hit_dice_max = max(ch.hit_dice_max, ch.level)
                ch.hit_dice_remaining = min(ch.hit_dice_max, ch.hit_dice_remaining + 1)
                # Queue a perk-picker. User gets /levelup button. Each pending
                # level-up adds one ability-score / power / proficiency perk.
                ch.pending_level_ups = int(ch.pending_level_ups or 0) + 1
                post_lines.append(
                    f"🎉 Новый уровень: {ch.level}! "
                    f"Нажми /levelup — выбрать перк."
                )

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

        # Grant a new universe-agnostic ability (spell / Force power / gadget).
        if plan.grant_ability and plan.grant_ability.name:
            if self._grant_ability_plain(ch, plan.grant_ability):
                post_lines.append(
                    f"✨ Новая способность: <b>{plan.grant_ability.name}</b> — /abilities."
                )

        # LLM narrated an ability use (rare; usually player uses /use). Spend
        # the charge so it doesn't become free.
        if plan.ability_use and plan.ability_use.name:
            ok, reason = engine.consume_power_charge(ch, plan.ability_use.name)
            if ok:
                post_lines.append(f"✨ Использовано: {reason}")
            else:
                post_lines.append(f"⚠ {reason}")

        # Structured quest events.
        for ev in plan.quest_events or []:
            line = await self._apply_quest_event(db, user, ev)
            if line:
                post_lines.append(line)

        # Companion additions / removals.
        if plan.add_companion and plan.add_companion.name:
            line = await self._apply_add_companion(db, user, plan.add_companion)
            if line:
                post_lines.append(line)
        if plan.remove_companion:
            line = await self._apply_remove_companion(db, user, plan.remove_companion)
            if line:
                post_lines.append(line)

        # NPC registry — persist named appearances so they exist in DB
        # beyond the 20-message sliding window. Without this, every callback
        # ("Зек умер ради тебя") fails because the engine forgot Zек existed.
        for npc_app in plan.npc_appearances or []:
            await self._upsert_npc_appearance(db, user, gs, npc_app)

        # Tension clock — decrement remaining turns on every active quest
        # with a deadline_turns counter. On 0, auto-fail and surface it.
        post_lines.extend(await self._tick_quest_deadlines(db, user))

        # Auto-archive long-stale quests so the journal stays scannable.
        await self._archive_stale_quests(db, user, gs.turn_number)

        # Auto-quest safety net — if the player is several turns in with
        # NO active quests and the LLM gave us a beat, mint a main quest
        # from the beat so /quests isn't empty. Prod data showed 0 quests
        # after 14 turns despite the GM clearly chasing a story arc.
        await self._auto_seed_quest_from_beat(db, user, gs, plan)

        # Low-HP hint — at ≤25% surface available consumables so the player
        # remembers to /use the stimpak instead of dying in the death loop.
        hint = self._low_hp_consumable_hint(ch)
        if hint:
            post_lines.append(hint)

        # Clean up dead enemies + close combat if the scene is empty.
        scene = [e for e in scene if int(e.get("hp_current", 0) or 0) > 0]
        if gs.combat_active and not scene:
            engine.end_combat(gs)
            # Encounter-scoped abilities refresh when combat ends.
            post_lines.extend(engine.refresh_powers(ch, "encounter"))
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

        # Beat-line — atomic "do this RIGHT NOW" goal that lives between
        # the after-effects and the options. Persistent reminder of what
        # the player should be trying to accomplish in this scene.
        beat = (plan.current_beat or "").strip()
        # Persist so /quest can echo it and the next turn's context can replay it.
        if beat:
            gs.current_beat = beat[:120]
        beat_line = f"🎯 <b>Сейчас:</b> {gs.current_beat}" if gs.current_beat else ""

        # Order: MECHANICS (pre) → NARRATIVE → AFTER-EFFECTS → BEAT-LINE.
        # User explicitly asked to see rolls & damage BEFORE the story text.
        parts = [x for x in (pre_block, body, post_block, beat_line) if x]
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
        ch.consecutive_death_turns = int(ch.consecutive_death_turns or 0) + 1
        lines: list[str] = [result.format()]

        if result.woke_up:
            _remove_cond(ch, "unconscious")
            ch.consecutive_death_turns = 0
            lines.append("✨ Ты приходишь в себя с 1 HP. Можешь действовать.")
            opts = self._ensure_options([
                "Подняться и оценить обстановку",
                "Лежать и восстановить дыхание",
                "Схватить первое попавшееся оружие",
                "Позвать на помощь",
            ])
        elif result.dead:
            _add_cond(ch, "dead")
            ch.consecutive_death_turns = 0
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
            # Pull the personal stake out of onboarding state if present —
            # this is the most emotionally loaded moment in the game and
            # the LLM never sees the death-save loop, so the engine has to
            # carry the weight itself.
            stake_hint = ""
            try:
                onb = json.loads(gs.onboarding_state_json or "{}")
                stake = (onb.get("stake") or "").strip() if isinstance(onb, dict) else ""
                if stake:
                    stake_hint = f"\n   <i>Если умрёшь — ты подведёшь: {stake}</i>"
            except Exception:
                pass
            lines.append(
                "…Ты без сознания. Дыхание ломается, перед глазами — лоскуты "
                "воспоминаний. На следующем ходу — очередной спасбросок."
                + stake_hint
            )
            opts = [
                "Продолжить (ещё спасбросок)",
                "Позвать на помощь (если рядом есть союзники)",
                "✏ Написать свой вариант",
            ]

        # If the player has been unconscious for 3+ consecutive turns and
        # combat was still flagged active, end it. Enemies don't sit around
        # forever watching a body bleed out. Without this, combat_active
        # stays true into the next scene and confuses every status line.
        if (
            gs.combat_active
            and int(ch.consecutive_death_turns or 0) >= 3
            and not result.woke_up
            and not result.dead
        ):
            engine.end_combat(gs)
            gs.scene_state_json = "[]"
            lines.append(
                "🏳 <i>Враги решают, что добивать тебя — пустая трата времени, "
                "и отступают. Бой окончен — ты остаёшься без сознания на месте.</i>"
            )

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

    # ─── Carry weight & attunement ────────────────────────────────────

    @staticmethod
    def format_carry(ch: Character) -> str:
        cap = engine.carrying_capacity_kg(ch)
        cur = engine.current_carry_weight_kg(ch)
        status = "⚠ Перегруз" if engine.is_encumbered(ch) else "в норме"
        return (
            f"🎒 <b>Нагрузка</b>: {cur:g} / {cap:g} кг ({status})\n"
            f"<i>Вес считается по полю <code>weight_kg</code> у предметов. "
            f"STR×7 — грузоподъёмность.</i>\n"
            f"Перегруз даёт помеху на STR/DEX/CON-проверки."
        )

    @staticmethod
    def format_attunement(ch: Character) -> str:
        items = engine.attuned_items(ch)
        mx = engine.attunement_max(ch)
        if not items:
            return (
                f"✨ <b>Настройка</b>: 0 / {mx}. "
                f"Нет настроенных предметов.\n"
                f"<i>Магические вещи (помеченные ✨) работают только после настройки.</i>\n"
                f"Команды: /attune &lt;предмет&gt;, /unattune &lt;предмет&gt;"
            )
        bullets = "\n".join(f" • ✨ {name}" for name in items)
        return (
            f"✨ <b>Настройка</b>: {len(items)} / {mx}\n{bullets}\n"
            f"<i>/unattune &lt;предмет&gt; — снять.</i>"
        )

    async def attune_item(self, db: AsyncSession, user: User, item_name: str) -> str:
        ch = await self.ensure_character(db, user)
        # Require item to exist and to be flagged as needing attunement.
        inv = json.loads(ch.inventory_json or "[]")
        low = (item_name or "").strip().lower()
        matching = next(
            (it for it in inv
             if low in (it.get("name") or "").lower()
             or (it.get("name") or "").lower() in low),
            None,
        )
        if not matching:
            return f"✨ Предмет «{item_name}» не найден в инвентаре."
        if not matching.get("requires_attunement"):
            return f"✨ «{matching.get('name')}» не требует настройки."
        ok, reason = engine.add_attunement(ch, matching["name"])
        return f"{'✅' if ok else '⚠'} {reason}"

    async def unattune_item(self, db: AsyncSession, user: User, item_name: str) -> str:
        ch = await self.ensure_character(db, user)
        ok, reason = engine.remove_attunement(ch, item_name)
        return f"{'✅' if ok else '⚠'} {reason}"

    # ─── Universe-agnostic abilities (spells / Force powers / gags) ──

    @staticmethod
    def format_abilities(ch: Character) -> str:
        return engine.format_powers(ch)

    @staticmethod
    def _grant_ability_plain(ch: Character, ability: Ability) -> bool:
        power = ability.model_dump()
        if int(power.get("current_uses", 0) or 0) == 0:
            power["current_uses"] = int(power.get("max_uses", 1) or 1)
        return engine.add_power(ch, power)

    async def use_ability(
        self, db: AsyncSession, user: User, ability_name: str,
    ) -> str:
        """Player-triggered `/use <name>`. Spends a charge, rolls dice if any,
        returns a human-readable result block. The actual narrative outcome
        is decided by the LLM on the next turn — we just handle mechanics.
        """
        ch = await self.ensure_character(db, user)
        power = engine.find_power(ch, ability_name)
        if not power:
            return (
                f"✨ Способность «{ability_name}» не найдена.\n"
                f"Список доступных — /abilities."
            )
        ok, reason = engine.consume_power_charge(ch, power["name"])
        if not ok:
            return f"⚠ {reason}"

        lines = [f"✨ <b>{power.get('emoji','✨')} {power['name']}</b> — активировано"]
        if power.get("description"):
            lines.append(f"<i>{power['description']}</i>")
        # Roll damage if any.
        if power.get("damage_dice"):
            total, expr = engine.roll_damage(power["damage_dice"])
            dtype = power.get("damage_type", "")
            lines.append(f"🎲 Урон: <code>{expr}</code> = <b>{total}</b>"
                         + (f" ({dtype})" if dtype else ""))
        if power.get("heal_dice"):
            total, expr = engine.roll_damage(power["heal_dice"])
            old, new = engine.apply_damage(ch, -total, damage_type="")
            lines.append(f"💚 Лечение: <code>{expr}</code> = <b>{total}</b> → HP {old} → {new}")
        if power.get("save_ability") and power.get("save_dc"):
            lines.append(
                f"🛡 Цель должна сделать сейв "
                f"<b>{power['save_ability']}</b> vs <b>DC {power['save_dc']}</b>"
            )
        refresh = power.get("refresh", "long")
        if refresh != "at_will":
            rem = int(power.get("current_uses", 0) or 0) - 1 + (1 if ok else 0)
            # Re-read after save:
            cur_power = engine.find_power(ch, power["name"])
            if cur_power:
                rem = int(cur_power.get("current_uses", 0) or 0)
            mx = int(power.get("max_uses", 1) or 1)
            lines.append(f"🔋 Зарядов осталось: {rem}/{mx}")
        lines.append("")
        lines.append("<i>Результат будет отыгран в следующей реплике ГМ.</i>")
        return "\n".join(lines)

    # ─── Quest journal ────────────────────────────────────────────────

    @staticmethod
    def _quest_title_similar(a: str, b: str) -> bool:
        """Loose match for quest titles. Catches the 'След крови / По следам
        сестры / След Чёрного Солнца' family — same arc, different wording.
        Strategy: lowercase + split into word stems (≥4 chars) and check
        whether ≥1 stem overlaps. Cheap heuristic, no NLP needed.
        """
        def stems(s: str) -> set[str]:
            return {
                w[:5] for w in re.findall(r"[\wа-яё]+", (s or "").lower())
                if len(w) >= 4
            }
        sa, sb = stems(a), stems(b)
        if not sa or not sb:
            return False
        return bool(sa & sb)

    async def _apply_quest_event(
        self, db: AsyncSession, user: User, event: QuestEvent,
    ) -> str:
        """Create / update / complete a Quest row from the LLM's structured
        event. Returns a short status line for the post-narrative block.
        """
        if not event.title:
            return ""
        title_low = event.title.strip().lower()
        existing = list(await db.scalars(
            select(Quest).where(Quest.user_id == user.id)
        ))
        row = next(
            (q for q in existing if q.title.strip().lower() == title_low),
            None,
        )
        action = (event.action or "create").lower()
        gs = await self.ensure_session(db, user)
        cur_turn = int(gs.turn_number or 0)

        if action == "create":
            if row:
                return ""  # exact title match — silent idempotency
            # Fuzzy merge: if there's an ACTIVE quest with overlapping
            # stems, treat this as an update rather than a new quest. Stops
            # the LLM from spawning "След крови" / "По следам сестры" as
            # two parallel quests when they're the same arc.
            for q in existing:
                if q.status != "active":
                    continue
                if self._quest_title_similar(event.title, q.title):
                    if event.description and event.description != q.description:
                        q.description = (q.description + "\n" + event.description).strip()[:2000]
                    if event.steps:
                        q.steps_json = json.dumps(
                            [s.model_dump() for s in event.steps],
                            ensure_ascii=False,
                        )
                    q.last_updated_turn = cur_turn
                    return f"📝 Квест обновлён: <b>{q.title}</b>"

            # Cooldown — limit how often new quests can spawn. Active GM
            # tends to over-generate; we throttle.
            last_create = int(gs.last_quest_create_turn or 0)
            if cur_turn > 0 and cur_turn - last_create < _QUEST_CREATE_COOLDOWN_TURNS:
                log.info("Quest create blocked by cooldown (turn %d, last %d): %s",
                         cur_turn, last_create, event.title)
                return ""

            q = Quest(
                user_id=user.id,
                title=event.title[:255],
                description=event.description or "",
                giver=event.giver or "",
                is_main=bool(event.is_main),
                status="active",
                steps_json=json.dumps(
                    [s.model_dump() for s in event.steps], ensure_ascii=False,
                ),
                reward_xp=int(event.reward_xp or 0),
                reward_gold=int(event.reward_gold or 0),
                deadline_turns_remaining=max(0, int(event.deadline_turns or 0)),
                last_updated_turn=cur_turn,
            )
            db.add(q)
            await db.flush()
            gs.last_quest_create_turn = cur_turn
            icon = "📜" if event.is_main else "📝"
            deadline_str = (
                f" ⏳ {event.deadline_turns} ходов"
                if event.deadline_turns and event.deadline_turns > 0 else ""
            )
            return f"{icon} Новый квест: <b>{event.title}</b>{deadline_str}"

        if not row:
            # silently ignore updates to nonexistent quests
            return ""

        if action == "update":
            if event.description:
                row.description = event.description
            if event.steps:
                row.steps_json = json.dumps(
                    [s.model_dump() for s in event.steps], ensure_ascii=False,
                )
            return f"📝 Квест обновлён: <b>{event.title}</b>"

        if action == "complete_step":
            try:
                steps = json.loads(row.steps_json or "[]")
            except Exception:
                steps = []
            key = (event.step_key_completed or "").strip().lower()
            for s in steps:
                if (s.get("key") or "").strip().lower() == key:
                    s["done"] = True
                    break
            row.steps_json = json.dumps(steps, ensure_ascii=False)
            row.last_updated_turn = cur_turn
            return f"✓ Шаг квеста «{event.title}»: {event.step_key_completed}"

        if action == "complete":
            row.status = "completed"
            row.last_updated_turn = cur_turn
            lines = [f"🏆 Квест завершён: <b>{event.title}</b>"]
            if row.reward_xp:
                ch = await self.ensure_character(db, user)
                ch.xp_current += row.reward_xp
                lines.append(f"   ⭐ +{row.reward_xp} XP")
            if row.reward_gold:
                ch = await self.ensure_character(db, user)
                ch.gold += row.reward_gold
                lines.append(f"   💰 +{row.reward_gold} золота")
            return "\n".join(lines)

        if action == "fail":
            row.status = "failed"
            row.last_updated_turn = cur_turn
            return f"💀 Квест провален: <b>{event.title}</b>"

        return ""

    @staticmethod
    def _append_json_list(field_json: str, item: str, cap: int = 8) -> str:
        """Append a short string to a JSON list column, keeping only the
        last `cap` entries. Dedups exact matches so the LLM can re-emit
        the same promise without it growing forever.
        """
        item = (item or "").strip()
        if not item:
            return field_json or "[]"
        try:
            data = json.loads(field_json or "[]")
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
        data = [x for x in data if str(x).strip() and str(x).strip() != item]
        data.append(item)
        return json.dumps(data[-cap:], ensure_ascii=False)

    async def _upsert_npc_appearance(
        self, db: AsyncSession, user: User, gs: GameSession, app,
    ) -> None:
        """Persist (or update) a named NPC seen this turn. Without this the
        engine forgets named characters as soon as they fall out of the
        20-message sliding window, killing callbacks.

        The NPC table is intentionally rich — bond, speech_style,
        appearance, promises[], debts[], secrets_known[], gifts_received[],
        last_quote, death_turn/cause. Every field is replayed into the
        system prompt so the LLM can write a real relationship instead of
        a flat name + role.
        """
        name = (getattr(app, "name", "") or "").strip()
        if not name:
            return
        row = await db.scalar(
            select(NPCState).where(
                NPCState.user_id == user.id,
                NPCState.name == name,
            )
        )
        cur_turn = int(gs.turn_number or 0)

        new_attitude = (getattr(app, "attitude", "") or "neutral")[:40]
        died = bool(getattr(app, "died", False))
        if died:
            new_attitude = "dead"

        if not row:
            row = NPCState(
                user_id=user.id,
                name=name[:255],
                current_location=gs.current_location,
                role=(getattr(app, "role", "") or "")[:120],
                attitude=new_attitude,
                notes=(getattr(app, "notes", "") or "")[:1000],
                faction=(getattr(app, "faction", "") or "")[:120],
                last_seen_turn=cur_turn,
                bond=max(-10, min(10, int(getattr(app, "bond_delta", 0) or 0))),
                speech_style=(getattr(app, "speech_style", "") or "")[:160],
                appearance=(getattr(app, "appearance", "") or "")[:2000],
                last_quote=(getattr(app, "last_quote", "") or "")[:1000],
            )
            if died:
                row.death_turn = cur_turn
                row.death_cause = (getattr(app, "death_cause", "") or "")[:255]
            # Seed the JSON lists.
            row.promises_json = self._append_json_list("[]", getattr(app, "add_promise", "") or "")
            row.debts_json = self._append_json_list("[]", getattr(app, "add_debt", "") or "")
            row.secrets_known_json = self._append_json_list("[]", getattr(app, "add_secret", "") or "")
            row.gifts_received_json = self._append_json_list("[]", getattr(app, "add_gift", "") or "")
            db.add(row)
            await db.flush()
            return

        # Existing — refresh ranking + accumulate relationship state.
        row.current_location = gs.current_location or row.current_location
        if getattr(app, "role", ""):
            row.role = (app.role or "")[:120]
        if new_attitude:
            row.attitude = new_attitude
        if getattr(app, "faction", ""):
            row.faction = (app.faction or "")[:120]
        if getattr(app, "notes", ""):
            merged = ((row.notes or "") + "\n" + (app.notes or "")).strip()
            row.notes = merged[-1000:]
        delta = int(getattr(app, "bond_delta", 0) or 0)
        if delta:
            row.bond = max(-10, min(10, int(row.bond or 0) + delta))
        if getattr(app, "speech_style", ""):
            row.speech_style = (app.speech_style or "")[:160]
        # Appearance — set once. Don't let the LLM rewrite a character's
        # face every time they walk on screen.
        if getattr(app, "appearance", "") and not row.appearance:
            row.appearance = (app.appearance or "")[:2000]
        if getattr(app, "last_quote", ""):
            row.last_quote = (app.last_quote or "")[:1000]
        # Accumulate event lists.
        row.promises_json = self._append_json_list(
            row.promises_json, getattr(app, "add_promise", "") or "")
        row.debts_json = self._append_json_list(
            row.debts_json, getattr(app, "add_debt", "") or "")
        row.secrets_known_json = self._append_json_list(
            row.secrets_known_json, getattr(app, "add_secret", "") or "")
        row.gifts_received_json = self._append_json_list(
            row.gifts_received_json, getattr(app, "add_gift", "") or "")
        if died and not row.death_turn:
            row.death_turn = cur_turn
            row.death_cause = (getattr(app, "death_cause", "") or "")[:255]
        row.last_seen_turn = cur_turn

    async def _tick_quest_deadlines(
        self, db: AsyncSession, user: User,
    ) -> list[str]:
        """Decrement deadline counters on active quests. On 0 → fail.
        Returns chat-facing lines for whatever happened.
        """
        lines: list[str] = []
        gs = await self.ensure_session(db, user)
        cur_turn = int(gs.turn_number or 0)
        active = list(await db.scalars(
            select(Quest).where(
                Quest.user_id == user.id, Quest.status == "active",
            )
        ))
        for q in active:
            d = int(q.deadline_turns_remaining or 0)
            if d <= 0:
                continue
            d -= 1
            q.deadline_turns_remaining = d
            if d == 0:
                q.status = "failed"
                q.last_updated_turn = cur_turn
                lines.append(f"⏳💀 Время вышло — квест провален: <b>{q.title}</b>")
            elif d <= 3:
                # Loud warning when the clock is about to run out.
                lines.append(f"⏳ <b>{q.title}</b> — осталось {d} ход(ов)")
        return lines

    async def _auto_seed_quest_from_beat(
        self, db: AsyncSession, user: User, gs: GameSession, plan: TurnPlan,
    ) -> None:
        """When the GM keeps narrating but hasn't created a single quest by
        turn 3, mint a main quest from the current beat so /quests isn't
        empty. Without this, players who never see a numeric goal feel
        like they're drifting (real prod data: 14-turn session, 0 quests).
        """
        cur_turn = int(gs.turn_number or 0)
        if cur_turn < 3:
            return
        existing = list(await db.scalars(
            select(Quest).where(
                Quest.user_id == user.id, Quest.status == "active",
            )
        ))
        if existing:
            return  # at least one active quest, don't intrude
        # Need SOMETHING to base the quest on. Prefer the LLM's quest_update
        # field (full sentence), fall back to the beat (short).
        seed = (plan.quest_update or "").strip() or (gs.current_beat or "").strip()
        if not seed:
            return
        title = seed[:80].rstrip(".,!?;:") + ("…" if len(seed) > 80 else "")
        q = Quest(
            user_id=user.id,
            title=title or "Главная задача",
            description=seed[:1000],
            is_main=True,
            status="active",
            last_updated_turn=cur_turn,
        )
        db.add(q)
        await db.flush()
        gs.last_quest_create_turn = cur_turn
        # No post_lines append — silent; the journal will surface it.

    @staticmethod
    def _low_hp_consumable_hint(ch: Character) -> str:
        """When the character is at ≤25% HP, surface healing consumables
        in inventory so the player notices them. Self-play showed players
        bleeding out with 2 stimpaks unused — the bot never reminded them.
        """
        hp_max = max(1, int(ch.hp_max or 1))
        if ch.hp_current / hp_max > 0.25:
            return ""
        try:
            inv = json.loads(ch.inventory_json or "[]")
        except Exception:
            inv = []
        HEAL_KEYWORDS = (
            "стимп", "зелье леч", "аптеч", "медкит", "бинт",
            "регенер", "инъекц", "стим", "healing potion",
        )
        heals = []
        for it in inv:
            name = (it.get("name") or "").strip()
            if not name:
                continue
            if any(k in name.lower() for k in HEAL_KEYWORDS):
                qty = int(it.get("quantity", 1) or 1)
                emoji = it.get("emoji") or "💊"
                heals.append(f"{emoji} {name} ×{qty}")
        if not heals:
            return ""
        return (
            f"⚠ <b>Низкое здоровье ({ch.hp_current}/{ch.hp_max} HP).</b> "
            f"Под рукой: {', '.join(heals)}. "
            f"<i>Используй: «выпиваю зелье», «колю стимпак», или /use.</i>"
        )

    async def _archive_stale_quests(
        self, db: AsyncSession, user: User, cur_turn: int,
    ) -> None:
        """Demote quests that haven't moved in _QUEST_STALE_TURNS turns from
        'active' to 'stale'. Keeps /quests scannable.
        """
        if cur_turn < _QUEST_STALE_TURNS:
            return
        cutoff = cur_turn - _QUEST_STALE_TURNS
        active = list(await db.scalars(
            select(Quest).where(
                Quest.user_id == user.id, Quest.status == "active",
            )
        ))
        for q in active:
            last = int(q.last_updated_turn or 0)
            if last and last < cutoff:
                q.status = "stale"

    async def format_quest_journal(self, db: AsyncSession, user: User) -> str:
        rows = list(await db.scalars(
            select(Quest).where(Quest.user_id == user.id)
        ))
        if not rows:
            return (
                "📜 <b>Журнал квестов</b>\n"
                "Записей пока нет. Новые квесты попадают сюда автоматически."
            )
        active = [q for q in rows if q.status == "active"]
        done = [q for q in rows if q.status == "completed"]
        failed = [q for q in rows if q.status == "failed"]

        def _fmt(q: Quest) -> str:
            icon = "📜" if q.is_main else "📝"
            line = f"{icon} <b>{q.title}</b>"
            if q.giver:
                line += f" <i>(от {q.giver})</i>"
            if q.description:
                line += f"\n   {q.description}"
            try:
                steps = json.loads(q.steps_json or "[]")
            except Exception:
                steps = []
            for s in steps:
                mark = "✓" if s.get("done") else "☐"
                line += f"\n   {mark} {s.get('description', s.get('key', '?'))}"
            if q.reward_xp or q.reward_gold:
                parts = []
                if q.reward_xp:
                    parts.append(f"{q.reward_xp} XP")
                if q.reward_gold:
                    parts.append(f"{q.reward_gold} зол.")
                line += f"\n   Награда: {', '.join(parts)}"
            return line

        out = ["📜 <b>Журнал квестов</b>"]
        if active:
            out.append("\n<b>Активные</b>")
            out.extend(_fmt(q) for q in active)
        if done:
            out.append("\n<b>Завершённые</b>")
            out.extend(_fmt(q) for q in done)
        if failed:
            out.append("\n<b>Провалены</b>")
            out.extend(_fmt(q) for q in failed)
        return "\n".join(out)

    # ─── Companions ───────────────────────────────────────────────────

    async def _apply_add_companion(
        self, db: AsyncSession, user: User, spec: CompanionSpec,
    ) -> str:
        if not spec.name:
            return ""
        existing = await db.scalar(
            select(NPCState).where(
                NPCState.user_id == user.id,
                NPCState.name == spec.name,
                NPCState.is_companion == True,  # noqa: E712
            )
        )
        if existing:
            return f"🤝 {spec.name} уже в отряде."
        npc = NPCState(
            user_id=user.id,
            name=spec.name,
            role=spec.role or "",
            hp_current=spec.hp_current or spec.hp_max or 10,
            hp_max=spec.hp_max or 10,
            ac=spec.ac or 12,
            attack_bonus=spec.attack_bonus or 3,
            damage_dice=spec.damage_dice or "1d6",
            damage_type=spec.damage_type or "",
            initiative_bonus=spec.initiative_bonus or 0,
            notes=spec.notes or "",
            attitude="ally",
            is_companion=True,
        )
        db.add(npc)
        await db.flush()
        return f"🤝 В отряде теперь: <b>{spec.name}</b>{(' — ' + spec.role) if spec.role else ''}"

    async def _apply_remove_companion(
        self, db: AsyncSession, user: User, name: str,
    ) -> str:
        row = await db.scalar(
            select(NPCState).where(
                NPCState.user_id == user.id,
                NPCState.name == name,
                NPCState.is_companion == True,  # noqa: E712
            )
        )
        if not row:
            return ""
        row.is_companion = False
        row.attitude = "neutral"
        return f"👋 {name} покинул отряд."

    async def format_companions(self, db: AsyncSession, user: User) -> str:
        rows = list(await db.scalars(
            select(NPCState).where(
                NPCState.user_id == user.id,
                NPCState.is_companion == True,  # noqa: E712
            )
        ))
        if not rows:
            return (
                "🤝 <b>Отряд</b>\n"
                "Ты путешествуешь в одиночку. Напарники появляются по сюжету."
            )
        lines = ["🤝 <b>Отряд</b>"]
        for n in rows:
            hp = f"{n.hp_current}/{n.hp_max}"
            line = f" • <b>{n.name}</b>"
            if n.role:
                line += f" — {n.role}"
            line += f"\n   ♥ {hp}  ⛨ КД {n.ac}  ⚔ +{n.attack_bonus} / {n.damage_dice}"
            if n.notes:
                line += f"\n   <i>{n.notes}</i>"
            lines.append(line)
        return "\n".join(lines)

    # ─── Level-up perk picker ─────────────────────────────────────────

    @staticmethod
    def _universe_aware_perk_pool(ch: Character, gs: GameSession) -> list[LevelUpPerk]:
        """Cheap, universe-agnostic fallback perk pool — always works even
        without the LLM. Real flavor comes from LLM-generated perks, but we
        keep this as a safety net so /levelup never fails.
        """
        stats = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        # Pick two lowest stats as targets for +1 so progression feels good.
        try:
            scores = json.loads(ch.abilities_json or "{}")
        except Exception:
            scores = {}
        ordered = sorted(stats, key=lambda k: int(scores.get(k, 10) or 10))
        stat_a = ordered[0]
        stat_b = ordered[1] if len(ordered) > 1 else ordered[0]
        ru = engine.ABILITY_RU
        perks: list[LevelUpPerk] = [
            LevelUpPerk(
                id="stat_a",
                label=f"+1 {ru.get(stat_a, stat_a)}",
                description=f"Повысить {ru.get(stat_a, stat_a)} на +1.",
                effect_type="stat", stat_key=stat_a, stat_delta=1,
            ),
            LevelUpPerk(
                id="stat_b",
                label=f"+1 {ru.get(stat_b, stat_b)}",
                description=f"Повысить {ru.get(stat_b, stat_b)} на +1.",
                effect_type="stat", stat_key=stat_b, stat_delta=1,
            ),
            LevelUpPerk(
                id="hp",
                label="+4 максимум HP",
                description="Увеличить максимальный запас здоровья на 4.",
                effect_type="hp", hp_delta=4,
            ),
        ]
        return perks

    async def propose_level_up_perks(
        self, db: AsyncSession, user: User, ch: Character, gs: GameSession,
    ) -> LevelUpOffer:
        """Build a LevelUpOffer. Asks Gemini for a setting-aware perk list;
        on any failure falls back to the deterministic universe-agnostic pool.
        """
        try:
            offer = await self.gemini.propose_level_up(ch, gs)
            if offer and offer.perks:
                offer.new_level = ch.level
                return offer
        except Exception:
            log.exception("propose_level_up LLM failure — using fallback pool")
        # Fallback: deterministic
        return LevelUpOffer(
            new_level=ch.level,
            flavor=f"Уровень {ch.level}! Пришло время расти.",
            perks=self._universe_aware_perk_pool(ch, gs),
        )

    async def apply_level_up_perk(
        self, db: AsyncSession, user: User, perk: LevelUpPerk,
    ) -> str:
        """Apply the picked perk to the character. Decrements pending_level_ups."""
        ch = await self.ensure_character(db, user)
        if int(ch.pending_level_ups or 0) <= 0:
            return "Нет ожидающих повышений."
        et = (perk.effect_type or "feature").lower()
        summary = ""
        if et == "stat" and perk.stat_key and perk.stat_delta:
            try:
                scores = json.loads(ch.abilities_json or "{}")
            except Exception:
                scores = {}
            key = perk.stat_key.upper()
            scores[key] = int(scores.get(key, 10) or 10) + int(perk.stat_delta)
            ch.abilities_json = json.dumps(scores, ensure_ascii=False)
            summary = f"📈 {engine.ABILITY_RU.get(key, key)} +{perk.stat_delta} → {scores[key]}"
        elif et == "hp" and perk.hp_delta:
            ch.hp_max += int(perk.hp_delta)
            ch.hp_current += int(perk.hp_delta)
            summary = f"♥ Максимум HP +{perk.hp_delta} (теперь {ch.hp_max})"
        elif et == "proficiency" and perk.proficiency_name:
            try:
                profs = json.loads(ch.skill_proficiencies_json or "[]")
            except Exception:
                profs = []
            name = perk.proficiency_name.strip().lower()
            if name and name not in [str(p).lower() for p in profs]:
                profs.append(name)
            ch.skill_proficiencies_json = json.dumps(profs, ensure_ascii=False)
            summary = f"🎯 Новое владение: {perk.proficiency_name}"
        elif et == "ability" and perk.granted_ability:
            added = self._grant_ability_plain(ch, perk.granted_ability)
            if added:
                summary = f"✨ Новая способность: {perk.granted_ability.name}"
            else:
                summary = f"✨ Способность «{perk.granted_ability.name}» уже была — заряды обновлены."
        else:
            summary = f"🎉 Перк «{perk.label}» применён."

        ch.pending_level_ups = max(0, int(ch.pending_level_ups or 0) - 1)
        return summary

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
