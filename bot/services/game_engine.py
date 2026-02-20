"""Deterministic DnD 5.5e rules engine.

All randomness and math lives here — Gemini never touches dice or numbers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from bot.models.character import Character
from bot.utils.dice import RollResult, roll

# --- XP thresholds (5.5e 2024) ---
XP_THRESHOLDS: dict[int, int] = {
    1: 0, 2: 300, 3: 900, 4: 2700, 5: 6500,
    6: 14000, 7: 23000, 8: 34000, 9: 48000, 10: 64000,
    11: 85000, 12: 100000, 13: 120000, 14: 140000, 15: 165000,
    16: 195000, 17: 225000, 18: 265000, 19: 305000, 20: 355000,
}

HIT_DIE: dict[str, str] = {
    "Barbarian": "d12", "Fighter": "d10", "Paladin": "d10", "Ranger": "d10",
    "Bard": "d8", "Cleric": "d8", "Druid": "d8", "Monk": "d8",
    "Rogue": "d8", "Warlock": "d8", "Sorcerer": "d6", "Wizard": "d6",
}

SKILL_ABILITY_MAP: dict[str, str] = {
    "Acrobatics": "dexterity", "Animal Handling": "wisdom", "Arcana": "intelligence",
    "Athletics": "strength", "Deception": "charisma", "History": "intelligence",
    "Insight": "wisdom", "Intimidation": "charisma", "Investigation": "intelligence",
    "Medicine": "wisdom", "Nature": "intelligence", "Perception": "wisdom",
    "Performance": "charisma", "Persuasion": "charisma", "Religion": "intelligence",
    "Sleight of Hand": "dexterity", "Stealth": "dexterity", "Survival": "wisdom",
}

# Russian skill name mapping for AI responses
SKILL_ABILITY_MAP_RU: dict[str, str] = {
    "Атлетика": "strength", "Акробатика": "dexterity", "Скрытность": "dexterity",
    "Ловкость рук": "dexterity", "Магия": "intelligence", "Анализ": "intelligence",
    "Расследование": "intelligence", "История": "intelligence", "Природа": "intelligence",
    "Религия": "intelligence", "Проницательность": "wisdom", "Внимательность": "wisdom",
    "Медицина": "wisdom", "Выживание": "wisdom", "Уход за животными": "wisdom",
    "Обман": "charisma", "Запугивание": "charisma", "Выступление": "charisma",
    "Убеждение": "charisma",
}

STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]

CLASS_STAT_PRIORITY: dict[str, list[str]] = {
    "Fighter":   ["strength", "constitution", "dexterity", "wisdom", "charisma", "intelligence"],
    "Wizard":    ["intelligence", "constitution", "dexterity", "wisdom", "charisma", "strength"],
    "Rogue":     ["dexterity", "charisma", "constitution", "intelligence", "wisdom", "strength"],
    "Cleric":    ["wisdom", "constitution", "strength", "charisma", "dexterity", "intelligence"],
    "Ranger":    ["dexterity", "wisdom", "constitution", "strength", "intelligence", "charisma"],
    "Paladin":   ["strength", "charisma", "constitution", "wisdom", "dexterity", "intelligence"],
    "Bard":      ["charisma", "dexterity", "constitution", "wisdom", "intelligence", "strength"],
    "Barbarian": ["strength", "constitution", "dexterity", "wisdom", "charisma", "intelligence"],
    "Monk":      ["dexterity", "wisdom", "constitution", "strength", "charisma", "intelligence"],
    "Sorcerer":  ["charisma", "constitution", "dexterity", "wisdom", "intelligence", "strength"],
    "Warlock":   ["charisma", "constitution", "dexterity", "wisdom", "intelligence", "strength"],
    "Druid":     ["wisdom", "constitution", "dexterity", "intelligence", "charisma", "strength"],
}

CLASS_SAVING_THROWS: dict[str, list[str]] = {
    "Fighter": ["strength", "constitution"], "Wizard": ["intelligence", "wisdom"],
    "Rogue": ["dexterity", "intelligence"], "Cleric": ["wisdom", "charisma"],
    "Ranger": ["strength", "dexterity"], "Paladin": ["wisdom", "charisma"],
    "Bard": ["dexterity", "charisma"], "Barbarian": ["strength", "constitution"],
    "Monk": ["strength", "dexterity"], "Sorcerer": ["constitution", "charisma"],
    "Warlock": ["wisdom", "charisma"], "Druid": ["intelligence", "wisdom"],
}

CLASS_STARTING_EQUIPMENT: dict[str, list[dict]] = {
    "Fighter": [
        {"name": "Longsword", "type": "weapon", "mechanics": {"damage": "1d8", "type": "slashing"}, "quantity": 1, "equipped": True},
        {"name": "Chain Mail", "type": "armor", "mechanics": {"ac": 16, "type": "heavy"}, "quantity": 1, "equipped": True},
        {"name": "Shield", "type": "armor", "mechanics": {"ac": 2, "type": "shield"}, "quantity": 1, "equipped": True},
        {"name": "Light Crossbow", "type": "weapon", "mechanics": {"damage": "1d8", "type": "piercing"}, "quantity": 1, "equipped": False},
        {"name": "Bolts", "type": "ammo", "quantity": 20, "equipped": False},
        {"name": "Explorer's Pack", "type": "misc", "description": "Backpack, bedroll, rations, rope, torches", "quantity": 1, "equipped": False},
    ],
    "Wizard": [
        {"name": "Quarterstaff", "type": "weapon", "mechanics": {"damage": "1d6", "type": "bludgeoning"}, "quantity": 1, "equipped": True},
        {"name": "Robes", "type": "armor", "mechanics": {"ac": 10, "type": "light"}, "quantity": 1, "equipped": True},
        {"name": "Spellbook", "type": "misc", "description": "Contains your prepared spells", "quantity": 1, "equipped": True},
        {"name": "Component Pouch", "type": "misc", "description": "Spell components", "quantity": 1, "equipped": True},
        {"name": "Scholar's Pack", "type": "misc", "description": "Ink, paper, small knife, book of lore", "quantity": 1, "equipped": False},
    ],
    "Rogue": [
        {"name": "Shortsword", "type": "weapon", "mechanics": {"damage": "1d6", "type": "piercing"}, "quantity": 1, "equipped": True},
        {"name": "Shortbow", "type": "weapon", "mechanics": {"damage": "1d6", "type": "piercing"}, "quantity": 1, "equipped": False},
        {"name": "Arrows", "type": "ammo", "quantity": 20, "equipped": False},
        {"name": "Leather Armor", "type": "armor", "mechanics": {"ac": 11, "type": "light"}, "quantity": 1, "equipped": True},
        {"name": "Thieves' Tools", "type": "misc", "description": "Lockpicks, wire, pliers", "quantity": 1, "equipped": True},
        {"name": "Burglar's Pack", "type": "misc", "description": "Rope, caltrops, grappling hook, dark clothes", "quantity": 1, "equipped": False},
    ],
    "Cleric": [
        {"name": "Mace", "type": "weapon", "mechanics": {"damage": "1d6", "type": "bludgeoning"}, "quantity": 1, "equipped": True},
        {"name": "Scale Mail", "type": "armor", "mechanics": {"ac": 14, "type": "medium"}, "quantity": 1, "equipped": True},
        {"name": "Shield", "type": "armor", "mechanics": {"ac": 2, "type": "shield"}, "quantity": 1, "equipped": True},
        {"name": "Holy Symbol", "type": "misc", "description": "Divine focus for spellcasting", "quantity": 1, "equipped": True},
        {"name": "Priest's Pack", "type": "misc", "description": "Holy water, candles, vestments, rations", "quantity": 1, "equipped": False},
    ],
    "Ranger": [
        {"name": "Longbow", "type": "weapon", "mechanics": {"damage": "1d8", "type": "piercing"}, "quantity": 1, "equipped": True},
        {"name": "Arrows", "type": "ammo", "quantity": 20, "equipped": False},
        {"name": "Shortsword", "type": "weapon", "mechanics": {"damage": "1d6", "type": "piercing"}, "quantity": 1, "equipped": True},
        {"name": "Studded Leather", "type": "armor", "mechanics": {"ac": 12, "type": "light"}, "quantity": 1, "equipped": True},
        {"name": "Explorer's Pack", "type": "misc", "description": "Rope, rations, torch, bedroll", "quantity": 1, "equipped": False},
    ],
    "Paladin": [
        {"name": "Longsword", "type": "weapon", "mechanics": {"damage": "1d8", "type": "slashing"}, "quantity": 1, "equipped": True},
        {"name": "Chain Mail", "type": "armor", "mechanics": {"ac": 16, "type": "heavy"}, "quantity": 1, "equipped": True},
        {"name": "Shield", "type": "armor", "mechanics": {"ac": 2, "type": "shield"}, "quantity": 1, "equipped": True},
        {"name": "Holy Symbol", "type": "misc", "description": "Divine focus", "quantity": 1, "equipped": True},
        {"name": "Priest's Pack", "type": "misc", "description": "Holy water, rations, vestments", "quantity": 1, "equipped": False},
    ],
    "Bard": [
        {"name": "Rapier", "type": "weapon", "mechanics": {"damage": "1d8", "type": "piercing"}, "quantity": 1, "equipped": True},
        {"name": "Leather Armor", "type": "armor", "mechanics": {"ac": 11, "type": "light"}, "quantity": 1, "equipped": True},
        {"name": "Lute", "type": "misc", "description": "Musical instrument, arcane focus", "quantity": 1, "equipped": True},
        {"name": "Diplomat's Pack", "type": "misc", "description": "Fine clothes, perfume, ink, paper", "quantity": 1, "equipped": False},
        {"name": "Dagger", "type": "weapon", "mechanics": {"damage": "1d4", "type": "piercing"}, "quantity": 1, "equipped": False},
    ],
    "Barbarian": [
        {"name": "Greataxe", "type": "weapon", "mechanics": {"damage": "1d12", "type": "slashing"}, "quantity": 1, "equipped": True},
        {"name": "Handaxe", "type": "weapon", "mechanics": {"damage": "1d6", "type": "slashing"}, "quantity": 2, "equipped": False},
        {"name": "Explorer's Pack", "type": "misc", "description": "Rope, rations, torches, bedroll", "quantity": 1, "equipped": False},
        {"name": "Javelin", "type": "weapon", "mechanics": {"damage": "1d6", "type": "piercing"}, "quantity": 4, "equipped": False},
    ],
    "Monk": [
        {"name": "Shortsword", "type": "weapon", "mechanics": {"damage": "1d6", "type": "piercing"}, "quantity": 1, "equipped": True},
        {"name": "Dart", "type": "weapon", "mechanics": {"damage": "1d4", "type": "piercing"}, "quantity": 10, "equipped": False},
        {"name": "Explorer's Pack", "type": "misc", "description": "Rope, rations, torches", "quantity": 1, "equipped": False},
    ],
    "Sorcerer": [
        {"name": "Light Crossbow", "type": "weapon", "mechanics": {"damage": "1d8", "type": "piercing"}, "quantity": 1, "equipped": True},
        {"name": "Bolts", "type": "ammo", "quantity": 20, "equipped": False},
        {"name": "Arcane Focus", "type": "misc", "description": "Crystal or orb for spellcasting", "quantity": 1, "equipped": True},
        {"name": "Explorer's Pack", "type": "misc", "description": "Rope, rations, torches", "quantity": 1, "equipped": False},
        {"name": "Dagger", "type": "weapon", "mechanics": {"damage": "1d4", "type": "piercing"}, "quantity": 2, "equipped": False},
    ],
    "Warlock": [
        {"name": "Light Crossbow", "type": "weapon", "mechanics": {"damage": "1d8", "type": "piercing"}, "quantity": 1, "equipped": True},
        {"name": "Bolts", "type": "ammo", "quantity": 20, "equipped": False},
        {"name": "Leather Armor", "type": "armor", "mechanics": {"ac": 11, "type": "light"}, "quantity": 1, "equipped": True},
        {"name": "Arcane Focus", "type": "misc", "description": "Pact token", "quantity": 1, "equipped": True},
        {"name": "Scholar's Pack", "type": "misc", "description": "Ink, paper, candles", "quantity": 1, "equipped": False},
    ],
    "Druid": [
        {"name": "Scimitar", "type": "weapon", "mechanics": {"damage": "1d6", "type": "slashing"}, "quantity": 1, "equipped": True},
        {"name": "Leather Armor", "type": "armor", "mechanics": {"ac": 11, "type": "light"}, "quantity": 1, "equipped": True},
        {"name": "Shield", "type": "armor", "mechanics": {"ac": 2, "type": "shield"}, "quantity": 1, "equipped": True},
        {"name": "Druidic Focus", "type": "misc", "description": "Totem or staff", "quantity": 1, "equipped": True},
        {"name": "Explorer's Pack", "type": "misc", "description": "Herbs, rations, rope", "quantity": 1, "equipped": False},
    ],
}

CLASS_STARTING_GOLD: dict[str, int] = {
    "Fighter": 15, "Wizard": 10, "Rogue": 20, "Cleric": 15,
    "Ranger": 15, "Paladin": 15, "Bard": 15, "Barbarian": 10,
    "Monk": 5, "Sorcerer": 10, "Warlock": 10, "Druid": 10,
}

CLASS_SPELL_SLOTS: dict[str, dict] = {
    "Wizard": {"1": {"current": 2, "max": 2}},
    "Sorcerer": {"1": {"current": 2, "max": 2}},
    "Cleric": {"1": {"current": 2, "max": 2}},
    "Bard": {"1": {"current": 2, "max": 2}},
    "Druid": {"1": {"current": 2, "max": 2}},
    "Warlock": {"1": {"current": 1, "max": 1}},
    "Paladin": {},
    "Ranger": {},
}

_KNOWN_CLASSES = list(CLASS_STAT_PRIORITY.keys())


def normalize_class_name(raw: str) -> str:
    """Map AI-provided class name (possibly in Russian or mixed) to canonical English name."""
    low = raw.lower().strip()
    _MAP = {
        "fighter": "Fighter", "воин": "Fighter", "боец": "Fighter",
        "wizard": "Wizard", "маг": "Wizard", "волшебник": "Wizard",
        "rogue": "Rogue", "плут": "Rogue", "разбойник": "Rogue", "вор": "Rogue",
        "cleric": "Cleric", "жрец": "Cleric", "клирик": "Cleric",
        "ranger": "Ranger", "следопыт": "Ranger", "рейнджер": "Ranger",
        "paladin": "Paladin", "паладин": "Paladin",
        "bard": "Bard", "бард": "Bard",
        "barbarian": "Barbarian", "варвар": "Barbarian",
        "monk": "Monk", "монах": "Monk",
        "sorcerer": "Sorcerer", "чародей": "Sorcerer", "колдун": "Sorcerer",
        "warlock": "Warlock", "чернокнижник": "Warlock", "колдун-пактист": "Warlock",
        "druid": "Druid", "друид": "Druid",
    }
    for key, canonical in _MAP.items():
        if key in low:
            return canonical
    return "Fighter"


def distribute_stats(char_class: str) -> dict[str, int]:
    priority = CLASS_STAT_PRIORITY.get(char_class, CLASS_STAT_PRIORITY["Fighter"])
    stats = {}
    for attr, val in zip(priority, STANDARD_ARRAY):
        stats[attr] = val
    return stats


def generate_starting_inventory(char_class: str) -> list[dict]:
    import copy
    items = CLASS_STARTING_EQUIPMENT.get(char_class, CLASS_STARTING_EQUIPMENT["Fighter"])
    return copy.deepcopy(items)


def calculate_ac(char: Character) -> int:
    """Calculate AC from equipped armor, porting web version logic."""
    dex_mod = char.dex_mod
    base_ac = 10 + dex_mod
    shield_bonus = 0

    for item in char.inventory:
        if not item.get("equipped"):
            continue
        if item.get("type") != "armor":
            continue
        mechanics = item.get("mechanics", {})
        if isinstance(mechanics, str):
            try:
                mechanics = json.loads(mechanics)
            except (json.JSONDecodeError, TypeError):
                mechanics = {}

        armor_type = str(mechanics.get("type", "")).lower()
        armor_ac = mechanics.get("ac", 0)
        if not armor_ac:
            continue

        name_lower = item.get("name", "").lower()
        is_shield = "shield" in name_lower or "щит" in name_lower or armor_type == "shield"

        if is_shield:
            shield_bonus += int(armor_ac)
        elif "heavy" in armor_type or "тяжел" in armor_type:
            base_ac = int(armor_ac)
        elif "medium" in armor_type or "средн" in armor_type:
            base_ac = int(armor_ac) + min(2, dex_mod)
        else:
            base_ac = int(armor_ac) + dex_mod

    return base_ac + shield_bonus


def build_full_character(
    char: Character,
    char_class: str,
    race: str = "Human",
    backstory: str = "",
    proficient_skills: list[str] | None = None,
    personality: str = "",
) -> None:
    """Apply all deterministic mechanics to a character after AI provides narrative fields."""
    canon_class = normalize_class_name(char_class)
    char.char_class = canon_class
    char.race = race
    char.level = 1

    stats = distribute_stats(canon_class)
    char.strength = stats["strength"]
    char.dexterity = stats["dexterity"]
    char.constitution = stats["constitution"]
    char.intelligence = stats["intelligence"]
    char.wisdom = stats["wisdom"]
    char.charisma = stats["charisma"]

    con_mod = (char.constitution - 10) // 2
    char.max_hp = max(1, calculate_starting_hp(canon_class, con_mod))
    char.current_hp = char.max_hp

    char.proficiency_bonus = proficiency_bonus(1)
    char.saving_throw_proficiencies = CLASS_SAVING_THROWS.get(canon_class, ["strength", "constitution"])

    if proficient_skills:
        char.proficient_skills = proficient_skills[:4]
    else:
        char.proficient_skills = []

    char.backstory = backstory
    char.inventory = generate_starting_inventory(canon_class)
    char.armor_class = calculate_ac(char)
    char.initiative_bonus = char.dex_mod
    char.speed = 30
    char.gold = CLASS_STARTING_GOLD.get(canon_class, 10)
    char.xp = 0

    hit_die = HIT_DIE.get(canon_class, "d8")
    char.hit_dice_current = 1
    char.hit_dice_max = 1
    char.hit_dice_face = hit_die

    char.spell_slots = CLASS_SPELL_SLOTS.get(canon_class, {})
    char.death_save_successes = 0
    char.death_save_failures = 0


def short_rest(char: Character) -> str:
    if char.current_hp >= char.max_hp:
        return "HP already full."
    if char.hit_dice_current <= 0:
        return "No hit dice remaining."

    die_face = char.hit_dice_face or "d8"
    result = roll(die_face, modifier=char.con_mod, reason="short rest")
    heal = max(0, result.total)
    old_hp = char.current_hp
    char.current_hp = min(char.max_hp, char.current_hp + heal)
    char.hit_dice_current = max(0, char.hit_dice_current - 1)
    healed = char.current_hp - old_hp
    return f"Short rest: healed {healed} HP ({result.display}). Hit Dice: {char.hit_dice_current}/{char.hit_dice_max}"


def long_rest(char: Character) -> str:
    old_hp = char.current_hp
    char.current_hp = char.max_hp
    healed = char.current_hp - old_hp

    recovered = max(1, char.hit_dice_max // 2)
    char.hit_dice_current = min(char.hit_dice_max, char.hit_dice_current + recovered)

    slots = char.spell_slots
    for lvl in slots:
        if isinstance(slots[lvl], dict) and "max" in slots[lvl]:
            slots[lvl]["current"] = slots[lvl]["max"]
    char.spell_slots = slots

    char.conditions = []
    char.death_save_successes = 0
    char.death_save_failures = 0

    return f"Long rest: HP {char.current_hp}/{char.max_hp} (+{healed}). Hit Dice: {char.hit_dice_current}/{char.hit_dice_max}. Spell slots restored."


def merge_inventory(existing: list[dict], changes: list[dict]) -> list[dict]:
    """Merge inventory changes by name (case-insensitive). Remove items with qty <= 0."""
    inv = {item.get("name", "").lower(): dict(item) for item in existing}
    for change in changes:
        name = change.get("name", "")
        key = name.lower()
        action = change.get("action", "add")
        if action == "remove":
            inv.pop(key, None)
        elif key in inv:
            inv[key]["quantity"] = inv[key].get("quantity", 1) + change.get("quantity", 1)
        else:
            inv[key] = dict(change)
            if "action" in inv[key]:
                del inv[key]["action"]
    return [item for item in inv.values() if item.get("quantity", 1) > 0]


def ensure_ammo(inventory: list[dict]) -> list[dict]:
    """Auto-add ammo if ranged weapon exists but no ammo present."""
    ranged_keywords = ["bow", "лук", "crossbow", "арбалет", "gun", "pistol", "rifle", "пистолет", "винтовка"]
    has_ranged = any(
        any(kw in item.get("name", "").lower() for kw in ranged_keywords)
        for item in inventory if item.get("type") == "weapon"
    )
    has_ammo = any(
        item.get("type") == "ammo" or "ammo" in item.get("name", "").lower()
        or "патрон" in item.get("name", "").lower() or "стрел" in item.get("name", "").lower()
        for item in inventory
    )
    if has_ranged and not has_ammo:
        inventory.append({
            "name": "Ammunition", "type": "ammo", "quantity": 20,
            "description": "Auto-added by system", "equipped": False,
        })
    return inventory


def proficiency_bonus(level: int) -> int:
    if level < 5:
        return 2
    if level < 9:
        return 3
    if level < 13:
        return 4
    if level < 17:
        return 5
    return 6


@dataclass
class AttackResult:
    attack_roll: RollResult
    hit: bool
    damage_roll: RollResult | None
    critical: bool

    @property
    def display(self) -> str:
        lines = [f"🎲 {self.attack_roll.display}"]
        if self.critical:
            lines.append("💥 CRITICAL HIT!")
        elif self.hit:
            lines.append("✅ Hit!")
        else:
            lines.append("❌ Miss!")
        if self.damage_roll:
            lines.append(f"⚔️ Damage: {self.damage_roll.display}")
        return "\n".join(lines)


@dataclass
class SkillCheckResult:
    roll_result: RollResult
    dc: int
    success: bool
    skill_name: str

    @property
    def display(self) -> str:
        tag = "✅ Success!" if self.success else "❌ Failure!"
        return f"🎲 {self.skill_name} check (DC {self.dc}): {self.roll_result.display}\n{tag}"


@dataclass
class SavingThrowResult:
    roll_result: RollResult
    dc: int
    success: bool
    ability: str

    @property
    def display(self) -> str:
        tag = "✅ Success!" if self.success else "❌ Failure!"
        return f"🎲 {self.ability} save (DC {self.dc}): {self.roll_result.display}\n{tag}"


@dataclass
class DeathSaveResult:
    roll_result: RollResult
    success: bool
    stabilized: bool
    dead: bool

    @property
    def display(self) -> str:
        if self.stabilized:
            return f"🎲 Death save: {self.roll_result.display}\n💚 Stabilized!"
        if self.dead:
            return f"🎲 Death save: {self.roll_result.display}\n💀 Dead..."
        tag = "✅" if self.success else "❌"
        return f"🎲 Death save: {self.roll_result.display} {tag}"


def make_attack(
    char: Character,
    target_ac: int,
    damage_dice: str = "1d8",
    ability: str = "strength",
    proficient: bool = True,
    advantage: bool = False,
    disadvantage: bool = False,
) -> AttackResult:
    ability_mod = char.ability_modifier(getattr(char, ability))
    atk_mod = ability_mod + (char.proficiency_bonus if proficient else 0)

    atk_roll = roll("1d20", modifier=atk_mod, advantage=advantage,
                     disadvantage=disadvantage, reason="attack")

    critical = atk_roll.natural_20
    hit = critical or atk_roll.total >= target_ac

    dmg_roll = None
    if hit:
        dice_to_roll = damage_dice
        if critical:
            parts = damage_dice.split("d")
            count = int(parts[0]) * 2
            dice_to_roll = f"{count}d{parts[1]}"
        dmg_roll = roll(dice_to_roll, modifier=ability_mod, reason="damage")

    return AttackResult(
        attack_roll=atk_roll, hit=hit, damage_roll=dmg_roll, critical=critical
    )


def skill_check(
    char: Character,
    skill_name: str,
    dc: int,
    advantage: bool = False,
    disadvantage: bool = False,
) -> SkillCheckResult:
    ability_name = SKILL_ABILITY_MAP.get(skill_name, "wisdom")
    ability_score = getattr(char, ability_name, 10)
    mod = char.ability_modifier(ability_score)
    if skill_name in char.proficient_skills:
        mod += char.proficiency_bonus

    result = roll("1d20", modifier=mod, advantage=advantage,
                  disadvantage=disadvantage, reason=skill_name)
    auto_success = result.natural_20
    auto_fail = result.natural_1
    success = auto_success or (not auto_fail and result.total >= dc)

    return SkillCheckResult(
        roll_result=result, dc=dc, success=success, skill_name=skill_name
    )


def saving_throw(
    char: Character,
    ability: str,
    dc: int,
    advantage: bool = False,
    disadvantage: bool = False,
) -> SavingThrowResult:
    ability_score = getattr(char, ability, 10)
    mod = char.ability_modifier(ability_score)
    if ability in char.saving_throw_proficiencies:
        mod += char.proficiency_bonus

    result = roll("1d20", modifier=mod, advantage=advantage,
                  disadvantage=disadvantage, reason=f"{ability} save")
    success = result.natural_20 or (not result.natural_1 and result.total >= dc)

    return SavingThrowResult(
        roll_result=result, dc=dc, success=success, ability=ability
    )


def death_saving_throw(char: Character) -> DeathSaveResult:
    result = roll("1d20", reason="death save")
    if result.natural_20:
        char.current_hp = 1
        char.death_save_successes = 0
        char.death_save_failures = 0
        return DeathSaveResult(
            roll_result=result, success=True, stabilized=True, dead=False
        )

    success = result.total >= 10
    if success:
        char.death_save_successes += 1
    else:
        char.death_save_failures += 1
        if result.natural_1:
            char.death_save_failures += 1

    stabilized = char.death_save_successes >= 3
    dead = char.death_save_failures >= 3

    if stabilized:
        char.death_save_successes = 0
        char.death_save_failures = 0
    if dead:
        char.death_save_successes = 0
        char.death_save_failures = 0

    return DeathSaveResult(
        roll_result=result, success=success, stabilized=stabilized, dead=dead
    )


def apply_damage(char: Character, damage: int) -> str:
    char.current_hp = max(0, char.current_hp - damage)
    if char.current_hp == 0:
        return "unconscious"
    return "alive"


def apply_healing(char: Character, healing: int) -> None:
    char.current_hp = min(char.max_hp, char.current_hp + healing)
    if char.current_hp > 0:
        char.death_save_successes = 0
        char.death_save_failures = 0


def grant_xp(char: Character, xp: int) -> bool:
    """Returns True if character leveled up."""
    char.xp += xp
    next_level = char.level + 1
    threshold = XP_THRESHOLDS.get(next_level)
    if threshold and char.xp >= threshold and char.level < 20:
        char.level = next_level
        char.proficiency_bonus = proficiency_bonus(next_level)
        _level_up_hp(char)
        return True
    return False


def _level_up_hp(char: Character) -> None:
    hit_die = HIT_DIE.get(char.char_class, "d8")
    hp_roll = roll(hit_die, modifier=char.con_mod, reason="level up HP")
    gained = max(1, hp_roll.total)
    char.max_hp += gained
    char.current_hp += gained


def calculate_starting_hp(char_class: str, con_modifier: int) -> int:
    hit_die = HIT_DIE.get(char_class, "d8")
    max_die = int(hit_die[1:])
    return max_die + con_modifier
