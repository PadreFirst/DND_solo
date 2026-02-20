"""Telegram message formatting: HP bars, stat blocks, dice displays."""
from __future__ import annotations

import re

from bot.models.character import Character
from bot.services.game_engine import XP_THRESHOLDS


def md_to_html(text: str) -> str:
    """Convert markdown bold/italic to HTML tags for Telegram.

    Also strips unsupported HTML tags to prevent parse errors.
    """
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<i>\1</i>', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    _allowed = {"b", "i", "u", "s", "code", "pre", "blockquote", "a"}
    def _filter_tag(m: re.Match) -> str:
        tag_content = m.group(1)
        tag_name = tag_content.split()[0].strip("/").lower()
        if tag_name in _allowed:
            return m.group(0)
        return ""
    text = re.sub(r'<(/?\w[^>]*)>', _filter_tag, text)
    return text


def progress_bar(current: int, maximum: int, length: int = 10) -> str:
    if maximum <= 0:
        return "░" * length
    ratio = max(0.0, min(1.0, current / maximum))
    filled = round(ratio * length)
    return "█" * filled + "░" * (length - filled)


def format_character_sheet(char: Character) -> str:
    next_lvl = char.level + 1
    xp_needed = XP_THRESHOLDS.get(next_lvl, 999999)
    hp_bar = progress_bar(char.current_hp, char.max_hp)
    xp_bar = progress_bar(char.xp, xp_needed)

    conditions_str = ", ".join(char.conditions) if char.conditions else "None"
    skills_str = ", ".join(char.proficient_skills) if char.proficient_skills else "None"

    inv_count = len(char.inventory)

    return (
        f"⚔️ <b>{char.name}</b> | {char.race} {char.char_class} Lv.{char.level}\n"
        f"\n"
        f"❤️ HP: {hp_bar} {char.current_hp}/{char.max_hp}\n"
        f"✨ XP: {xp_bar} {char.xp}/{xp_needed}\n"
        f"🛡 AC: {char.armor_class}  |  ⚡ Init: {char.initiative_bonus:+d}  |  🦶 Speed: {char.speed}\n"
        f"\n"
        f"<b>STR</b> {char.strength} ({char.str_mod:+d})  "
        f"<b>DEX</b> {char.dexterity} ({char.dex_mod:+d})  "
        f"<b>CON</b> {char.constitution} ({char.con_mod:+d})\n"
        f"<b>INT</b> {char.intelligence} ({char.int_mod:+d})  "
        f"<b>WIS</b> {char.wisdom} ({char.wis_mod:+d})  "
        f"<b>CHA</b> {char.charisma} ({char.cha_mod:+d})\n"
        f"\n"
        f"🎯 Proficiency: +{char.proficiency_bonus}\n"
        f"📋 Skills: {skills_str}\n"
        f"💀 Conditions: {conditions_str}\n"
        f"\n"
        f"🎒 Items: {inv_count}  |  💰 Gold: {char.gold}\n"
        f"🎲 Hit Dice: {char.hit_dice_current}/{char.hit_dice_max} ({char.hit_dice_face})"
    )


_TYPE_ICONS = {
    "weapon": "⚔️", "armor": "🛡", "consumable": "🧪",
    "ammo": "🏹", "misc": "📦",
}


def format_inventory(char: Character) -> str:
    if not char.inventory:
        return "🎒 <b>Inventory</b>\n\n<i>Empty</i>"

    equipped_lines = []
    other_lines = []
    for i, item in enumerate(char.inventory, 1):
        name = item.get("name", "???")
        qty = item.get("quantity", 1)
        itype = item.get("type", "misc")
        icon = _TYPE_ICONS.get(itype, "📦")
        mechanics = item.get("mechanics", {})
        if isinstance(mechanics, str):
            import json
            try:
                mechanics = json.loads(mechanics)
            except Exception:
                mechanics = {}

        detail = ""
        if itype == "weapon" and mechanics:
            detail = f" [{mechanics.get('damage', '')} {mechanics.get('type', '')}]"
        elif itype == "armor" and mechanics:
            detail = f" [AC {mechanics.get('ac', '')}, {mechanics.get('type', '')}]"

        qty_str = f" x{qty}" if qty > 1 else ""
        line = f"{icon} {name}{detail}{qty_str}"

        if item.get("equipped"):
            equipped_lines.append(line)
        else:
            other_lines.append(line)

    parts = ["🎒 <b>Inventory</b>\n"]
    if equipped_lines:
        parts.append("<b>Equipped:</b>")
        parts.extend(equipped_lines)
        parts.append("")
    if other_lines:
        parts.append("<b>Backpack:</b>")
        parts.extend(other_lines)

    parts.append(f"\n💰 Gold: {char.gold}")
    return "\n".join(parts)


def format_dice_roll(dice_str: str, rolls: list[int], modifier: int, total: int,
                     reason: str = "", nat20: bool = False, nat1: bool = False) -> str:
    rolls_display = ", ".join(str(r) for r in rolls)
    mod_str = f" {modifier:+d}" if modifier else ""
    result = f"🎲 {reason}: " if reason else "🎲 "
    result += f"{dice_str}{mod_str} = [{rolls_display}]{mod_str} = <b>{total}</b>"
    if nat20:
        result += " 🌟 <b>NAT 20!</b>"
    elif nat1:
        result += " 💀 <b>NAT 1!</b>"
    return result


def format_quest(quest_text: str, location: str) -> str:
    return (
        f"📜 <b>Current Quest</b>\n\n"
        f"{quest_text}\n\n"
        f"📍 Location: <b>{location}</b>"
    )


def truncate_for_telegram(text: str, max_length: int = 4000) -> str:
    """Telegram messages max out at 4096 chars. Leave room for formatting."""
    if len(text) <= max_length:
        return text
    cut = text[:max_length - 20]
    open_tag = cut.rfind("<")
    close_tag = cut.rfind(">")
    if open_tag > close_tag:
        cut = cut[:open_tag]
    for tag in ("b", "i", "u", "s", "code", "pre", "blockquote"):
        opens = cut.count(f"<{tag}>") + cut.count(f"<{tag} ")
        closes = cut.count(f"</{tag}>")
        for _ in range(opens - closes):
            cut += f"</{tag}>"
    return cut + "..."
