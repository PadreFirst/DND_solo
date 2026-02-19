"""Deterministic DnD 5.5e rules engine.

All randomness and math lives here — Gemini never touches dice or numbers.
"""
from __future__ import annotations

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
    "Barbarian": "d12",
    "Fighter": "d10",
    "Paladin": "d10",
    "Ranger": "d10",
    "Bard": "d8",
    "Cleric": "d8",
    "Druid": "d8",
    "Monk": "d8",
    "Rogue": "d8",
    "Warlock": "d8",
    "Sorcerer": "d6",
    "Wizard": "d6",
}

SKILL_ABILITY_MAP: dict[str, str] = {
    "Acrobatics": "dexterity",
    "Animal Handling": "wisdom",
    "Arcana": "intelligence",
    "Athletics": "strength",
    "Deception": "charisma",
    "History": "intelligence",
    "Insight": "wisdom",
    "Intimidation": "charisma",
    "Investigation": "intelligence",
    "Medicine": "wisdom",
    "Nature": "intelligence",
    "Perception": "wisdom",
    "Performance": "charisma",
    "Persuasion": "charisma",
    "Religion": "intelligence",
    "Sleight of Hand": "dexterity",
    "Stealth": "dexterity",
    "Survival": "wisdom",
}


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
