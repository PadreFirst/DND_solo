"""Tests for Batch C: faction reputation, attunement, carrying, passive PP."""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from bot.services.engine import (
    add_attunement,
    attuned_items,
    attunement_max,
    carrying_capacity_kg,
    current_carry_weight_kg,
    is_encumbered,
    is_social_skill,
    make_skill_check,
    passive_perception,
    remove_attunement,
    reputation_modifier,
)


@dataclass
class FakeCharacter:
    name: str = "Герой"
    hp_current: int = 20
    hp_max: int = 20
    temp_hp: int = 0
    ac: int = 14
    speed_m: int = 9
    proficiency_bonus: int = 2
    level: int = 1
    abilities_json: str = '{"STR":12,"DEX":14,"CON":13,"INT":10,"WIS":14,"CHA":10}'
    skill_proficiencies_json: str = '["внимательность","убеждение"]'
    saving_throw_proficiencies_json: str = '["DEX","CON"]'
    conditions_json: str = "[]"
    resistances_json: str = '{"resist":[],"immune":[],"vulnerable":[]}'
    death_saves_success: int = 0
    death_saves_failure: int = 0
    hit_dice_remaining: int = 1
    hit_dice_max: int = 1
    inventory_json: str = "[]"
    attunement_json: str = '{"max":3,"items":[]}'


@dataclass
class FakeSession:
    weather: str = "clear"
    time_of_day: str = "day"
    has_light_source: bool = True


# ─── Passive perception ──────────────────────────────────────────────────

class TestPassivePerception:
    def test_pp_with_proficiency_counts_prof_bonus(self):
        ch = FakeCharacter()  # WIS 14 → +2; proficient in внимательность → +2 prof
        assert passive_perception(ch) == 10 + 2 + 2

    def test_pp_without_proficiency_is_base_only(self):
        ch = FakeCharacter(skill_proficiencies_json='["атлетика"]')
        # WIS 14 → +2 mod, no prof
        assert passive_perception(ch) == 10 + 2

    def test_pp_high_wis_score(self):
        ch = FakeCharacter(
            abilities_json='{"STR":12,"DEX":14,"CON":13,"INT":10,"WIS":18,"CHA":10}',
        )
        assert passive_perception(ch) == 10 + 4 + 2


# ─── Carrying weight ─────────────────────────────────────────────────────

class TestCarryingWeight:
    def test_capacity_is_str_times_seven(self):
        ch = FakeCharacter()  # STR 12 → 84 kg
        assert carrying_capacity_kg(ch) == 84

    def test_current_weight_sums_qty_times_weight(self):
        ch = FakeCharacter(inventory_json=json.dumps([
            {"name": "Меч", "quantity": 1, "weight_kg": 2.0},
            {"name": "Болт", "quantity": 20, "weight_kg": 0.05},
            {"name": "Паёк", "quantity": 2, "weight_kg": 1.0},
        ]))
        assert current_carry_weight_kg(ch) == 2.0 + 20 * 0.05 + 2.0  # = 5.0

    def test_encumbered_true_when_over_capacity(self):
        ch = FakeCharacter(
            abilities_json='{"STR":8,"DEX":14,"CON":13,"INT":10,"WIS":14,"CHA":10}',
            inventory_json=json.dumps([{"name": "Наковальня", "quantity": 1, "weight_kg": 100}]),
        )
        # STR 8 × 7 = 56 kg, carrying 100 → overloaded
        assert is_encumbered(ch) is True

    def test_not_encumbered_empty_inventory(self):
        ch = FakeCharacter()
        assert is_encumbered(ch) is False

    def test_encumbrance_applies_disadvantage_on_str_check(self):
        ch = FakeCharacter(
            abilities_json='{"STR":8,"DEX":14,"CON":13,"INT":10,"WIS":14,"CHA":10}',
            inventory_json=json.dumps([{"name": "Груз", "quantity": 1, "weight_kg": 500}]),
        )
        rich = make_skill_check(ch, "атлетика", 10)
        assert rich.disadvantage is True
        assert "перегруз" in rich.reasons


# ─── Faction reputation ──────────────────────────────────────────────────

class TestReputationModifier:
    def test_neutral_no_mod(self):
        assert reputation_modifier(0) == 0
        assert reputation_modifier(19) == 0
        assert reputation_modifier(-19) == 0

    def test_friendly_plus_one(self):
        assert reputation_modifier(25) == 1

    def test_allied_plus_two(self):
        assert reputation_modifier(60) == 2

    def test_revered_plus_three(self):
        assert reputation_modifier(90) == 3
        assert reputation_modifier(100) == 3

    def test_hostile_negative(self):
        assert reputation_modifier(-60) == -2
        assert reputation_modifier(-90) == -3

    def test_social_skill_detection(self):
        assert is_social_skill("убеждение") is True
        assert is_social_skill("Обман") is True  # case-insensitive
        assert is_social_skill("атлетика") is False

    def test_social_check_with_high_rep_applies_bonus(self):
        ch = FakeCharacter()
        rich = make_skill_check(ch, "убеждение", 15, reputation_score=90)
        # Prof bonus includes rep modifier (+3)
        assert any("репутация +3" in r for r in rich.reasons)

    def test_social_check_with_bad_rep_applies_penalty(self):
        ch = FakeCharacter()
        rich = make_skill_check(ch, "убеждение", 15, reputation_score=-80)
        assert any("репутация -3" in r for r in rich.reasons)

    def test_non_social_check_ignores_reputation(self):
        ch = FakeCharacter()
        rich = make_skill_check(ch, "атлетика", 10, reputation_score=90)
        assert not any("репутация" in r for r in rich.reasons)

    def test_no_reputation_supplied_no_modifier(self):
        ch = FakeCharacter()
        rich = make_skill_check(ch, "убеждение", 15)  # no rep passed
        assert not any("репутация" in r for r in rich.reasons)


# ─── Attunement ──────────────────────────────────────────────────────────

class TestAttunement:
    def test_empty_attunement_starts_at_zero(self):
        ch = FakeCharacter()
        assert attuned_items(ch) == []
        assert attunement_max(ch) == 3

    def test_add_one_item_ok(self):
        ch = FakeCharacter()
        ok, _ = add_attunement(ch, "Амулет")
        assert ok is True
        assert "Амулет" in attuned_items(ch)

    def test_adding_duplicate_rejected(self):
        ch = FakeCharacter(attunement_json='{"max":3,"items":["Амулет"]}')
        ok, reason = add_attunement(ch, "Амулет")
        assert ok is False
        assert "уже" in reason.lower()

    def test_fourth_item_rejected(self):
        ch = FakeCharacter(attunement_json='{"max":3,"items":["A","B","C"]}')
        ok, reason = add_attunement(ch, "D")
        assert ok is False
        assert "лимит" in reason.lower()

    def test_remove_existing_ok(self):
        ch = FakeCharacter(attunement_json='{"max":3,"items":["Амулет","Кольцо"]}')
        ok, _ = remove_attunement(ch, "Кольцо")
        assert ok is True
        assert "Кольцо" not in attuned_items(ch)
        assert "Амулет" in attuned_items(ch)

    def test_remove_missing_item_fails(self):
        ch = FakeCharacter()
        ok, _ = remove_attunement(ch, "Плащ")
        assert ok is False
