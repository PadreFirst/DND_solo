"""Telegram message formatting: HP bars, stat blocks, dice displays."""
from __future__ import annotations

import re

from bot.models.character import Character
from bot.services.game_engine import XP_THRESHOLDS


def md_to_html(text: str) -> str:
    """Convert markdown bold/italic to HTML tags for Telegram."""
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<i>\1</i>', text)
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
        f"🎒 Items: {inv_count}  |  💰 Gold: {char.gold}"
    )


def format_inventory(char: Character) -> str:
    if not char.inventory:
        return "🎒 <b>Inventory</b>\n\n<i>Empty</i>"

    lines = ["🎒 <b>Inventory</b>\n"]
    for i, item in enumerate(char.inventory, 1):
        name = item.get("name", "???")
        qty = item.get("quantity", 1)
        desc = item.get("description", "")
        qty_str = f" x{qty}" if qty > 1 else ""
        desc_str = f" — <i>{desc}</i>" if desc else ""
        lines.append(f"{i}. {name}{qty_str}{desc_str}")

    lines.append(f"\n💰 Gold: {char.gold}")
    return "\n".join(lines)


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
    return text[:max_length - 3] + "..."
