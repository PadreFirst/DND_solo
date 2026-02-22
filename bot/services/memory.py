"""Context / memory management.

Builds the prompt context window from DB state, recent messages,
summarized history, and episodic memories.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.character import Character
from bot.models.game_session import GameSession
from bot.models.memory import Memory
from bot.models.user import User
from bot.services.gemini import generate_text

log = logging.getLogger(__name__)


def _mod_str(score: int) -> str:
    mod = (score - 10) // 2
    return f"{score}({mod:+d})"


async def build_context(
    user: User,
    char: Character,
    session: GameSession,
    db: AsyncSession,
) -> str:
    """Assemble the full context block that goes into every Gemini request."""
    parts: list[str] = []

    parts.append(_build_system_info(char))
    parts.append(_build_world_block(session))
    parts.append(await _build_memory_block(user.id, db))

    if session.summary:
        parts.append(f"=== STORY SO FAR (summary) ===\n{session.summary}")

    recent = session.get_recent_messages(settings.max_recent_messages)
    if recent:
        msg_text = "\n".join(
            f"{'PLAYER' if m['role'] == 'user' else 'GAME MASTER'}: {m['content']}"
            for m in recent
        )
        parts.append(f"=== RECENT CONVERSATION ===\n{msg_text}")

    parts.append(_build_preferences_block(user))

    return "\n\n".join(p for p in parts if p)


def _build_system_info(char: Character) -> str:
    """Structured [SYSTEM INFO] block — single source of truth for the AI."""
    equipped_items = []
    inv_items = []
    for item in char.inventory:
        name = item.get("name", "???")
        qty = item.get("quantity", 1)
        itype = item.get("type", "misc")
        mechanics = item.get("mechanics", {})
        if isinstance(mechanics, str):
            try:
                mechanics = json.loads(mechanics)
            except (json.JSONDecodeError, TypeError):
                mechanics = {}

        detail = ""
        if itype == "weapon" and mechanics:
            detail = f" ({mechanics.get('damage', '')} {mechanics.get('type', '')})"
        elif itype == "armor" and mechanics:
            detail = f" (AC {mechanics.get('ac', '')}, {mechanics.get('type', '')})"

        label = f"{name}{detail}" + (f" x{qty}" if qty > 1 else "")

        if item.get("equipped"):
            equipped_items.append(label)
        else:
            inv_items.append(label)

    conditions = char.conditions
    cond_str = ", ".join(conditions) if conditions else "None"

    spell_slots = char.spell_slots
    slots_parts = []
    for lvl in sorted(spell_slots.keys()):
        slot = spell_slots[lvl]
        if isinstance(slot, dict):
            slots_parts.append(f"{lvl}: {slot.get('current', 0)}/{slot.get('max', 0)}")

    lines = [
        "[SYSTEM INFO]",
        f"Player: {char.name}, Level {char.level} {char.race} {char.char_class}",
        f"HP: {char.current_hp}/{char.max_hp}, AC: {char.armor_class}",
        f"Attributes: STR {_mod_str(char.strength)} DEX {_mod_str(char.dexterity)} "
        f"CON {_mod_str(char.constitution)} INT {_mod_str(char.intelligence)} "
        f"WIS {_mod_str(char.wisdom)} CHA {_mod_str(char.charisma)}",
        f"Proficiency: +{char.proficiency_bonus}",
        f"Skills: {', '.join(char.proficient_skills) or 'None'}",
        f"Saves: {', '.join(char.saving_throw_proficiencies) or 'None'}",
        f"Equipped: {', '.join(equipped_items) or 'None'}",
        f"Inventory: {', '.join(inv_items) or 'Empty'}",
        f"Gold: {char.gold}",
        f"Hit Dice: {char.hit_dice_current}/{char.hit_dice_max} ({char.hit_dice_face})",
        f"Conditions: {cond_str}",
        f"XP: {char.xp}",
    ]
    if slots_parts:
        lines.append(f"Spell Slots: {', '.join(slots_parts)}")

    abilities = char.abilities
    if abilities:
        active = [a for a in abilities if a.get("type") == "active"]
        passive = [a for a in abilities if a.get("type") == "passive"]
        if active:
            active_str = ", ".join(f"{a['name']} ({a.get('desc', '')})" for a in active)
            lines.append(f"Active Abilities: {active_str}")
        if passive:
            passive_str = ", ".join(f"{a['name']} ({a.get('desc', '')})" for a in passive)
            lines.append(f"Passive Abilities: {passive_str}")

    if char.backstory:
        lines.append(f"Backstory: {char.backstory[:300]}")
    lines.append("[/SYSTEM INFO]")
    return "\n".join(lines)


def _build_world_block(session: GameSession) -> str:
    state = session.to_state_dict()
    currency = getattr(session, "currency_name", None) or "gold"
    state["currency"] = currency
    return (
        f"=== WORLD STATE (source of truth) ===\n"
        f"{json.dumps(state, indent=2, ensure_ascii=False)}"
    )


async def _build_memory_block(user_id: int, db: AsyncSession) -> str:
    result = await db.execute(
        select(Memory)
        .where(Memory.user_id == user_id)
        .order_by(Memory.importance.desc(), Memory.created_at.desc())
        .limit(15)
    )
    memories = result.scalars().all()
    if not memories:
        return ""
    lines = [f"=== KEY MEMORIES ==="]
    for m in memories:
        lines.append(f"[{m.category}] {m.content} (importance: {m.importance})")
    return "\n".join(lines)


def _build_preferences_block(user: User) -> str:
    return (
        f"=== PLAYER PREFERENCES ===\n"
        f"Language: {user.language}\n"
        f"Content tier: {user.content_tier.value}\n"
        f"Combat interest: {user.combat_pref:.1f} | "
        f"Puzzles: {user.puzzle_pref:.1f} | "
        f"Dialogue: {user.dialogue_pref:.1f} | "
        f"Exploration: {user.exploration_pref:.1f}\n"
        f"Romance tolerance: {user.romance_tolerance:.1f} | "
        f"Gore tolerance: {user.gore_tolerance:.1f} | "
        f"Humor: {user.humor_pref:.1f}\n"
        f"Engagement: {user.engagement_level:.1f}"
    )


async def maybe_summarize(session: GameSession, content_tier: str) -> None:
    """If enough messages accumulated, summarize older ones."""
    if session.message_count < settings.summarize_every_n:
        return
    if session.message_count % settings.summarize_every_n != 0:
        return

    history = session.message_history
    cutoff = len(history) - settings.max_recent_messages
    if cutoff <= 0:
        return

    old_messages = history[:cutoff]
    old_text = "\n".join(
        f"{'PLAYER' if m['role'] == 'user' else 'GM'}: {m['content']}"
        for m in old_messages
    )

    prompt = (
        f"Summarize the following DnD game conversation into a concise narrative "
        f"summary (300 words max). Preserve ALL important plot points, NPC names, "
        f"locations visited, items found, decisions made, and combat outcomes. "
        f"Do NOT lose any critical information.\n\n"
        f"Previous summary:\n{session.summary or '(none)'}\n\n"
        f"New messages to integrate:\n{old_text}"
    )

    new_summary = await generate_text(prompt, content_tier=content_tier, temperature=0.3)
    session.summary = new_summary.strip()
    session.message_history = history[cutoff:]
    log.info("Summarized %d old messages for user session %d", cutoff, session.user_id)


async def save_episodic_memory(
    user_id: int,
    category: str,
    content: str,
    importance: int,
    db: AsyncSession,
) -> None:
    mem = Memory(
        user_id=user_id,
        category=category,
        content=content,
        importance=min(10, max(1, importance)),
    )
    db.add(mem)
    await db.flush()
