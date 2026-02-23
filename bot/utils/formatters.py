"""Telegram message formatting: HP bars, stat blocks, dice displays."""
from __future__ import annotations

import re

from bot.models.character import Character
from bot.services.game_engine import XP_THRESHOLDS


def md_to_html(text: str) -> str:
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


def compact_stat_bar(char: Character, lang: str = "en", currency: str = "", concentration: str = "") -> str:
    cur = currency or ("зол." if lang == "ru" else "g")
    bar = (
        f"❤️ {char.current_hp}/{char.max_hp} HP"
        f" | 🛡 AC {char.armor_class}"
        f" | ⭐ Lv.{char.level}"
        f" | 💰 {char.gold} {cur}"
    )
    if concentration:
        bar += f" | 🔮 {concentration}"
    return bar


_L = {
    "ru": {
        "skills": "Навыки", "active": "Активные", "passive": "Пассивные",
        "conditions": "Состояния", "items": "Предметы", "gold": "Золото",
        "hit_dice": "Кости хитов", "prof": "Мастерство", "equipped": "Экипировано",
        "backpack": "Рюкзак", "inventory": "Инвентарь", "empty": "Пусто",
        "spell_slots": "Ячейки заклинаний", "none_val": "нет",
        "damage": "Урон", "defense": "Защита", "quantity": "Количество",
        "equipped_tag": "Экипировано",
    },
    "en": {
        "skills": "Skills", "active": "Active", "passive": "Passive",
        "conditions": "Conditions", "items": "Items", "gold": "Gold",
        "hit_dice": "Hit Dice", "prof": "Proficiency", "equipped": "Equipped",
        "backpack": "Backpack", "inventory": "Inventory", "empty": "Empty",
        "spell_slots": "Spell Slots", "none_val": "None",
        "damage": "Damage", "defense": "Defense", "quantity": "Quantity",
        "equipped_tag": "Equipped",
    },
}


def _lbl(lang: str, key: str) -> str:
    return _L.get(lang, _L["en"]).get(key, _L["en"].get(key, key))


def format_character_sheet(char: Character, lang: str = "en", currency: str = "") -> str:
    next_lvl = char.level + 1
    xp_needed = XP_THRESHOLDS.get(next_lvl, 999999)
    hp_bar = progress_bar(char.current_hp, char.max_hp)
    xp_bar = progress_bar(char.xp, xp_needed)

    conditions_str = ", ".join(char.conditions) if char.conditions else "—"
    skills_str = ", ".join(char.proficient_skills) if char.proficient_skills else "—"
    cur_label = currency or _lbl(lang, "gold")

    lines = [
        f"⚔️ <b>{char.name}</b> | {char.race} {char.char_class} Lv.{char.level}",
        f"",
        f"❤️ HP: {hp_bar} {char.current_hp}/{char.max_hp}",
        f"✨ XP: {xp_bar} {char.xp}/{xp_needed}",
        f"🛡 AC: {char.armor_class}  |  ⚡ Init: {char.initiative_bonus:+d}  |  🦶 Speed: {char.speed}",
        f"",
        f"<b>STR</b> {char.strength} ({char.str_mod:+d})  "
        f"<b>DEX</b> {char.dexterity} ({char.dex_mod:+d})  "
        f"<b>CON</b> {char.constitution} ({char.con_mod:+d})",
        f"<b>INT</b> {char.intelligence} ({char.int_mod:+d})  "
        f"<b>WIS</b> {char.wisdom} ({char.wis_mod:+d})  "
        f"<b>CHA</b> {char.charisma} ({char.cha_mod:+d})",
        f"",
        f"🎯 {_lbl(lang, 'prof')}: +{char.proficiency_bonus}",
        f"📋 {_lbl(lang, 'skills')}: {skills_str}",
    ]

    abilities = char.abilities
    if abilities:
        active = [a for a in abilities if a.get("type") == "active"]
        passive = [a for a in abilities if a.get("type") == "passive"]
        if active:
            active_str = ", ".join(f"<b>{a['name']}</b>" for a in active)
            lines.append(f"⚡ {_lbl(lang, 'active')}: {active_str}")
        if passive:
            passive_str = ", ".join(a["name"] for a in passive)
            lines.append(f"🔹 {_lbl(lang, 'passive')}: {passive_str}")

    lines.extend([
        f"💀 {_lbl(lang, 'conditions')}: {conditions_str}",
        f"",
        f"🎒 {_lbl(lang, 'items')}: {len(char.inventory)}  |  💰 {cur_label}: {char.gold}",
        f"🎲 {_lbl(lang, 'hit_dice')}: {char.hit_dice_current}/{char.hit_dice_max} ({char.hit_dice_face})",
    ])

    return "\n".join(lines)


_TYPE_ICONS = {
    "weapon": "⚔️", "armor": "🛡", "consumable": "🧪",
    "ammo": "🏹", "misc": "📦",
}


def format_inventory(char: Character, lang: str = "en", currency: str = "") -> str:
    cur_label = currency or _lbl(lang, "gold")

    if not char.inventory:
        return f"🎒 <b>{_lbl(lang, 'inventory')}</b>\n\n<i>{_lbl(lang, 'empty')}</i>"

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

    parts = [f"🎒 <b>{_lbl(lang, 'inventory')}</b>\n"]
    if equipped_lines:
        parts.append(f"<b>{_lbl(lang, 'equipped')}:</b>")
        parts.extend(equipped_lines)
        parts.append("")
    if other_lines:
        parts.append(f"<b>{_lbl(lang, 'backpack')}:</b>")
        parts.extend(other_lines)

    parts.append(f"\n💰 {cur_label}: {char.gold}")
    return "\n".join(parts)


_RECHARGE_RU = {
    "at will": "без ограничений",
    "short rest": "короткий отдых",
    "long rest": "длинный отдых",
    "per turn": "раз в ход",
    "spell slots": "ячейки заклинаний",
    "per short rest": "короткий отдых",
    "per long rest": "длинный отдых",
}


def format_ability_card(ability: dict, lang: str = "en") -> str:
    name = ability.get("name", "???")
    atype = ability.get("type", "active")
    recharge = ability.get("recharge", "")
    desc = ability.get("desc", "")

    type_label = {"active": "⚡ Активная" if lang == "ru" else "⚡ Active",
                  "passive": "🔹 Пассивная" if lang == "ru" else "🔹 Passive"}
    lines = [f"<b>{name}</b>"]
    lines.append(type_label.get(atype, atype))
    if recharge:
        if lang == "ru":
            recharge = _RECHARGE_RU.get(recharge.lower().strip(), recharge)
        r_label = "Перезарядка" if lang == "ru" else "Recharge"
        lines.append(f"🔄 {r_label}: {recharge}")
    if desc:
        lines.append(f"\n<i>{desc}</i>")
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
