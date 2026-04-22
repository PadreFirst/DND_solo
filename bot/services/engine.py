from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from bot.models import Character
from bot.services.dice import RollResult, roll_dice

SKILL_TO_ABILITY = {
    "атлетика": "STR",
    "акробатика": "DEX",
    "скрытность": "DEX",
    "ловкость рук": "DEX",
    "магия": "INT",
    "история": "INT",
    "анализ": "INT",
    "природа": "INT",
    "религия": "INT",
    "внимательность": "WIS",
    "проницательность": "WIS",
    "медицина": "WIS",
    "выживание": "WIS",
    "уход за животными": "WIS",
    "убеждение": "CHA",
    "обман": "CHA",
    "запугивание": "CHA",
    "выступление": "CHA",
}

ABILITY_RU = {
    "STR": "Сил", "DEX": "Лов", "CON": "Тел",
    "INT": "Инт", "WIS": "Мдр", "CHA": "Хар",
}


@dataclass
class RichRoll:
    """Detailed roll breakdown for user-facing display."""
    label: str
    d20: int
    d20_alt: int | None  # second die for advantage/disadvantage
    advantage: bool
    disadvantage: bool
    ability_key: str
    ability_mod_value: int
    proficiency_value: int  # 0 if not proficient
    total: int
    dc: int
    success: bool

    def format(self, *, kind: str = "Проверка") -> str:
        parts: list[str] = []

        if self.d20_alt is not None:
            tag = "преим." if self.advantage else "помеха"
            chosen = max(self.d20, self.d20_alt) if self.advantage else min(self.d20, self.d20_alt)
            parts.append(f"d20[{self.d20},{self.d20_alt}]→{chosen} ({tag})")
            base_d20 = chosen
        else:
            parts.append(f"d20={self.d20}")
            base_d20 = self.d20

        ab_short = ABILITY_RU.get(self.ability_key, self.ability_key)
        if self.ability_mod_value != 0:
            parts.append(f"{ab_short} {self.ability_mod_value:+d}")
        else:
            parts.append(f"{ab_short} +0")

        if self.proficiency_value:
            parts.append(f"мастерство {self.proficiency_value:+d}")

        dc_label = "КД" if kind == "Атака" else "DC"
        result = "Успех" if self.success else "Провал"
        if kind == "Атака":
            result = "Попадание" if self.success else "Промах"

        return f"🎲 {kind} {self.label}: {', '.join(parts)} → {self.total} vs {dc_label} {self.dc} — {result}"


def ability_mod(character: Character, key: str) -> int:
    abilities = json.loads(character.abilities_json or "{}")
    score = int(abilities.get(key.upper(), 10))
    return (score - 10) // 2


def make_skill_check(
    character: Character,
    skill_name: str,
    dc: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> RichRoll:
    key = SKILL_TO_ABILITY.get(skill_name.strip().lower(), "WIS")
    mod = ability_mod(character, key)
    profs = [s.lower() for s in json.loads(character.skill_proficiencies_json or "[]")]
    prof_bonus = character.proficiency_bonus if skill_name.strip().lower() in profs else 0
    total_mod = mod + prof_bonus

    d20, d20_alt = _roll_d20(advantage, disadvantage)
    chosen = _pick_d20(d20, d20_alt, advantage, disadvantage)
    total = chosen + total_mod

    return RichRoll(
        label=skill_name.capitalize(),
        d20=d20, d20_alt=d20_alt,
        advantage=advantage and not disadvantage,
        disadvantage=disadvantage and not advantage,
        ability_key=key, ability_mod_value=mod,
        proficiency_value=prof_bonus,
        total=total, dc=dc, success=total >= dc,
    )


def make_attack_roll(
    character: Character,
    target_ac: int,
    *,
    ability_key: str = "STR",
    advantage: bool = False,
    disadvantage: bool = False,
    label: str = "атака",
) -> RichRoll:
    mod = ability_mod(character, ability_key)
    prof_bonus = character.proficiency_bonus

    d20, d20_alt = _roll_d20(advantage, disadvantage)
    chosen = _pick_d20(d20, d20_alt, advantage, disadvantage)
    total = chosen + mod + prof_bonus

    return RichRoll(
        label=label,
        d20=d20, d20_alt=d20_alt,
        advantage=advantage and not disadvantage,
        disadvantage=disadvantage and not advantage,
        ability_key=ability_key, ability_mod_value=mod,
        proficiency_value=prof_bonus,
        total=total, dc=target_ac, success=total >= target_ac,
    )


def make_save_roll(
    character: Character,
    ability_key: str,
    dc: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> RichRoll:
    mod = ability_mod(character, ability_key)
    save_profs = [s.upper() for s in json.loads(character.saving_throw_proficiencies_json or "[]")]
    prof_bonus = character.proficiency_bonus if ability_key.upper() in save_profs else 0

    d20, d20_alt = _roll_d20(advantage, disadvantage)
    chosen = _pick_d20(d20, d20_alt, advantage, disadvantage)
    total = chosen + mod + prof_bonus

    ab_label = ABILITY_RU.get(ability_key.upper(), ability_key)
    return RichRoll(
        label=ab_label,
        d20=d20, d20_alt=d20_alt,
        advantage=advantage and not disadvantage,
        disadvantage=disadvantage and not advantage,
        ability_key=ability_key, ability_mod_value=mod,
        proficiency_value=prof_bonus,
        total=total, dc=dc, success=total >= dc,
    )


def apply_hp_change(character: Character, delta: int) -> tuple[int, int]:
    """delta < 0 damage, delta > 0 heal. Returns old,new."""
    old = character.hp_current
    if delta < 0:
        remaining_damage = abs(delta)
        if character.temp_hp > 0:
            absorbed = min(character.temp_hp, remaining_damage)
            character.temp_hp -= absorbed
            remaining_damage -= absorbed
        character.hp_current = max(0, character.hp_current - remaining_damage)
    elif delta > 0:
        character.hp_current = min(character.hp_max, character.hp_current + delta)
    return old, character.hp_current


def _roll_d20(advantage: bool, disadvantage: bool) -> tuple[int, int | None]:
    if advantage or disadvantage:
        a = random.randint(1, 20)
        b = random.randint(1, 20)
        if advantage and disadvantage:
            return a, None  # cancel out → single roll
        return a, b
    return random.randint(1, 20), None


def _pick_d20(d20: int, d20_alt: int | None, advantage: bool, disadvantage: bool) -> int:
    if d20_alt is None:
        return d20
    if advantage and not disadvantage:
        return max(d20, d20_alt)
    if disadvantage and not advantage:
        return min(d20, d20_alt)
    return d20
