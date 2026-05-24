"""Tests for the DND game engine mechanics."""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from bot.services.engine import (
    ABILITY_RU,
    RichRoll,
    ability_mod,
    apply_hp_change,
    make_attack_roll,
    make_save_roll,
    make_skill_check,
)


@dataclass
class FakeCharacter:
    """Lightweight stand-in for Character ORM."""
    hp_current: int = 12
    hp_max: int = 12
    temp_hp: int = 0
    ac: int = 14
    proficiency_bonus: int = 2
    level: int = 1
    abilities_json: str = '{"STR":16,"DEX":14,"CON":13,"INT":10,"WIS":12,"CHA":8}'
    skill_proficiencies_json: str = '["атлетика","внимательность"]'
    saving_throw_proficiencies_json: str = '["STR","CON"]'
    xp_current: int = 0
    xp_to_next_level: int = 300
    gold: int = 25


class TestAbilityMod:
    def test_str_16(self):
        ch = FakeCharacter()
        assert ability_mod(ch, "STR") == 3

    def test_dex_14(self):
        ch = FakeCharacter()
        assert ability_mod(ch, "DEX") == 2

    def test_cha_8(self):
        ch = FakeCharacter()
        assert ability_mod(ch, "CHA") == -1

    def test_missing_ability_defaults_to_10(self):
        ch = FakeCharacter()
        assert ability_mod(ch, "NONEXIST") == 0


class TestSkillCheck:
    def test_proficient_skill_returns_rich_roll(self):
        ch = FakeCharacter()
        rr = make_skill_check(ch, "атлетика", dc=10)
        assert isinstance(rr, RichRoll)
        assert rr.ability_key == "STR"
        assert rr.ability_mod_value == 3
        assert rr.proficiency_value == 2
        # d20 range: 1-20, total = d20 + 3 + 2 = [6, 25]
        assert 6 <= rr.total <= 25

    def test_non_proficient_skill(self):
        ch = FakeCharacter()
        rr = make_skill_check(ch, "обман", dc=10)
        assert rr.ability_key == "CHA"
        assert rr.ability_mod_value == -1
        assert rr.proficiency_value == 0
        assert 0 <= rr.total <= 19

    def test_unknown_skill_uses_wis(self):
        ch = FakeCharacter()
        rr = make_skill_check(ch, "несуществующий_навык", dc=10)
        assert rr.ability_key == "WIS"

    def test_format_output(self):
        ch = FakeCharacter()
        rr = make_skill_check(ch, "атлетика", dc=12)
        # Default = one-liner (verbose=False).
        text = rr.format(kind="Проверка")
        assert "Проверка" in text
        assert "DC 12" in text
        assert "Успех" in text or "Провал" in text
        # Verbose mode renders the full breakdown.
        verbose = rr.format(kind="Проверка", verbose=True)
        assert "d20:" in verbose
        assert "Сила" in verbose
        assert "Мастерство" in verbose


class TestAttackRoll:
    def test_attack_roll_rich(self):
        ch = FakeCharacter()
        rr = make_attack_roll(ch, target_ac=15, ability_key="STR", label="удар мечом")
        assert isinstance(rr, RichRoll)
        assert rr.ability_mod_value == 3
        assert rr.proficiency_value == 2
        assert 6 <= rr.total <= 25

    def test_format_attack(self):
        ch = FakeCharacter()
        rr = make_attack_roll(ch, target_ac=14, ability_key="STR", label="меч")
        text = rr.format(kind="Атака")
        assert "Атака" in text
        assert "КД 14" in text


class TestSaveRoll:
    def test_proficient_save(self):
        ch = FakeCharacter()
        rr = make_save_roll(ch, "STR", dc=12)
        assert rr.proficiency_value == 2
        assert 6 <= rr.total <= 25

    def test_non_proficient_save(self):
        ch = FakeCharacter()
        rr = make_save_roll(ch, "CHA", dc=12)
        assert rr.proficiency_value == 0
        assert 0 <= rr.total <= 19

    def test_format_save(self):
        ch = FakeCharacter()
        rr = make_save_roll(ch, "CON", dc=14)
        text = rr.format(kind="Спасбросок")
        assert "Спасбросок" in text
        assert "DC 14" in text


class TestApplyHpChange:
    def test_damage(self):
        ch = FakeCharacter(hp_current=12, hp_max=12, temp_hp=0)
        old, new = apply_hp_change(ch, -5)
        assert old == 12
        assert new == 7

    def test_heal(self):
        ch = FakeCharacter(hp_current=5, hp_max=12, temp_hp=0)
        old, new = apply_hp_change(ch, 4)
        assert old == 5
        assert new == 9

    def test_heal_capped_at_max(self):
        ch = FakeCharacter(hp_current=10, hp_max=12, temp_hp=0)
        old, new = apply_hp_change(ch, 100)
        assert new == 12

    def test_damage_floor_at_zero(self):
        ch = FakeCharacter(hp_current=3, hp_max=12, temp_hp=0)
        old, new = apply_hp_change(ch, -10)
        assert new == 0

    def test_temp_hp_absorbs_damage(self):
        ch = FakeCharacter(hp_current=10, hp_max=12, temp_hp=5)
        old, new = apply_hp_change(ch, -7)
        assert ch.temp_hp == 0
        assert new == 8

    def test_temp_hp_partial_absorb(self):
        ch = FakeCharacter(hp_current=10, hp_max=12, temp_hp=3)
        old, new = apply_hp_change(ch, -10)
        assert ch.temp_hp == 0
        assert new == 3

    def test_zero_delta(self):
        ch = FakeCharacter(hp_current=10, hp_max=12, temp_hp=0)
        old, new = apply_hp_change(ch, 0)
        assert old == 10
        assert new == 10


class TestRichRollFormat:
    def test_basic_format(self):
        rr = RichRoll(
            label="Внимательность", d20=14, d20_alt=None,
            advantage=False, disadvantage=False,
            ability_key="WIS", ability_mod_value=1, proficiency_value=2,
            total=17, dc=12, success=True,
        )
        # Default = compact one-liner (verbose=False).
        text = rr.format(kind="Проверка")
        assert "Проверка: Внимательность" in text
        assert "17" in text and "DC 12" in text
        assert "Успех" in text
        assert "на 5 больше" in text
        # Verbose breakdown — header, d20, ability, proficiency, total.
        v = rr.format(kind="Проверка", verbose=True)
        assert "d20:" in v
        assert "14" in v
        assert "Мудрость" in v and "+1" in v
        assert "Мастерство" in v and "+2" in v

    def test_attack_format(self):
        rr = RichRoll(
            label="удар мечом", d20=15, d20_alt=None,
            advantage=False, disadvantage=False,
            ability_key="STR", ability_mod_value=3, proficiency_value=2,
            total=20, dc=14, success=True,
        )
        text = rr.format(kind="Атака")
        assert "Попадание" in text
        assert "КД 14" in text
        assert "Сила" in text and "+3" in text

    def test_advantage_format(self):
        rr = RichRoll(
            label="Скрытность", d20=14, d20_alt=8,
            advantage=True, disadvantage=False,
            ability_key="DEX", ability_mod_value=2, proficiency_value=0,
            total=16, dc=15, success=True,
        )
        # Advantage/disadvantage details live in the verbose breakdown.
        text = rr.format(kind="Проверка", verbose=True)
        assert "преимущество" in text
        assert "14" in text and "8" in text

    def test_negative_mod(self):
        rr = RichRoll(
            label="Обман", d20=10, d20_alt=None,
            advantage=False, disadvantage=False,
            ability_key="CHA", ability_mod_value=-1, proficiency_value=0,
            total=9, dc=12, success=False,
        )
        # Failure verdict + margin show up in the one-liner.
        text = rr.format(kind="Проверка")
        assert "Провал" in text
        assert "не хватило" in text
        # Negative-mod detail lives in the verbose breakdown.
        v = rr.format(kind="Проверка", verbose=True)
        assert "Харизма" in v and "-1" in v

    def test_zero_mod(self):
        rr = RichRoll(
            label="Анализ", d20=10, d20_alt=None,
            advantage=False, disadvantage=False,
            ability_key="INT", ability_mod_value=0, proficiency_value=0,
            total=10, dc=10, success=True,
        )
        # +0 mod label only appears in verbose mode.
        v = rr.format(kind="Проверка", verbose=True)
        assert "Интеллект" in v and "+0" in v

    def test_crit_attack_format(self):
        """Natural 20 on an attack must show a big visual CRIT marker."""
        rr = RichRoll(
            label="меч", d20=20, d20_alt=None,
            advantage=False, disadvantage=False,
            ability_key="STR", ability_mod_value=3, proficiency_value=2,
            total=25, dc=13, success=True,
        )
        text = rr.format(kind="Атака")
        assert "КРИТ" in text
        assert "💥" in text
        assert "КРИТИЧЕСКОЕ ПОПАДАНИЕ" in text

    def test_fumble_check_format(self):
        """Natural 1 on a skill check shows fumble marker."""
        rr = RichRoll(
            label="Скрытность", d20=1, d20_alt=None,
            advantage=False, disadvantage=False,
            ability_key="DEX", ability_mod_value=2, proficiency_value=0,
            total=3, dc=12, success=False,
        )
        text = rr.format(kind="Проверка")
        assert "ФУМБЛ" in text
        assert "💀" in text


class TestHpBar:
    def test_full_hp(self):
        from bot.services.engine import hp_bar
        bar = hp_bar(10, 10, width=10)
        assert "10/10" in bar
        assert "▰" * 10 in bar
        assert "▱" not in bar

    def test_half_hp(self):
        from bot.services.engine import hp_bar
        bar = hp_bar(5, 10, width=10)
        assert "5/10" in bar
        assert "▰" * 5 in bar
        assert "▱" * 5 in bar

    def test_zero_hp(self):
        from bot.services.engine import hp_bar
        bar = hp_bar(0, 10, width=10)
        assert "0/10" in bar
        assert "▱" * 10 in bar


class TestDamageBreakdown:
    def test_renders_dice_mod_total(self):
        from bot.services.engine import format_damage_breakdown
        out = format_damage_breakdown(
            "1d8+2", rolls=[6], flat_mod=2, total=8,
            critical=False, damage_type="slashing", ability_label="Сила",
        )
        assert "Урон" in out
        assert "1d8" in out
        assert "[6]" in out
        assert "Сила" in out
        assert "+2" in out
        assert "8" in out
        assert "🗡" in out  # slashing emoji
        assert "рубящий" in out

    def test_crit_marker(self):
        from bot.services.engine import format_damage_breakdown
        out = format_damage_breakdown(
            "1d8+2", rolls=[6, 4], flat_mod=2, total=12,
            critical=True, damage_type="piercing", ability_label="Ловкость",
        )
        assert "крит" in out.lower() or "💥" in out

    def test_damage_type_emoji_known(self):
        from bot.services.engine import format_damage_type
        assert format_damage_type("fire").startswith("🔥")
        assert "огонь" in format_damage_type("fire")

    def test_damage_type_unknown(self):
        from bot.services.engine import format_damage_type
        assert format_damage_type("") == ""
        assert "psychic_blast" in format_damage_type("psychic_blast")
