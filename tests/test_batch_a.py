"""Tests for Batch A: auto-modifiers, damage types, death saves, rest."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from bot.services.engine import (
    apply_damage,
    compute_auto_modifiers,
    make_attack_roll,
    make_skill_check,
    perform_long_rest,
    perform_short_rest,
    roll_death_save,
)


@dataclass
class FakeCharacter:
    hp_current: int = 12
    hp_max: int = 12
    temp_hp: int = 0
    ac: int = 14
    proficiency_bonus: int = 2
    level: int = 1
    abilities_json: str = '{"STR":16,"DEX":14,"CON":13,"INT":10,"WIS":12,"CHA":8}'
    skill_proficiencies_json: str = '["атлетика","внимательность"]'
    saving_throw_proficiencies_json: str = '["STR","CON"]'
    conditions_json: str = "[]"
    resistances_json: str = '{"resist":[],"immune":[],"vulnerable":[]}'
    death_saves_success: int = 0
    death_saves_failure: int = 0
    hit_dice_remaining: int = 1
    hit_dice_max: int = 1


@dataclass
class FakeSession:
    weather: str = "clear"
    time_of_day: str = "day"
    has_light_source: bool = True


class TestConditionModifiers:
    def test_poisoned_gives_disadvantage_on_attack(self):
        ch = FakeCharacter(conditions_json='["poisoned"]')
        _, dis, reasons = compute_auto_modifiers(ch, None, roll_kind="attack", label="удар мечом")
        assert dis is True
        assert "poisoned" in reasons

    def test_blinded_gives_disadvantage_on_attack(self):
        ch = FakeCharacter(conditions_json='["blinded"]')
        _, dis, _ = compute_auto_modifiers(ch, None, roll_kind="attack", label="выстрел")
        assert dis is True

    def test_invisible_gives_advantage_on_attack(self):
        ch = FakeCharacter(conditions_json='["invisible"]')
        adv, _, _ = compute_auto_modifiers(ch, None, roll_kind="attack", label="удар")
        assert adv is True

    def test_adv_plus_dis_cancel_out(self):
        # invisible (adv) + blinded (dis)
        ch = FakeCharacter(conditions_json='["invisible","blinded"]')
        adv, dis, _ = compute_auto_modifiers(ch, None, roll_kind="attack", label="удар")
        assert adv is False
        assert dis is False

    def test_restrained_disadvantage_on_dex_save(self):
        ch = FakeCharacter(conditions_json='["restrained"]')
        _, dis, _ = compute_auto_modifiers(ch, None, roll_kind="save", label="", ability_key="DEX")
        assert dis is True

    def test_no_conditions_no_modifiers(self):
        ch = FakeCharacter()
        adv, dis, reasons = compute_auto_modifiers(ch, None, roll_kind="attack", label="удар")
        assert adv is False and dis is False and reasons == []


class TestEnvironmentModifiers:
    def test_fog_disadvantages_ranged_attack(self):
        ch = FakeCharacter()
        gs = FakeSession(weather="fog")
        _, dis, reasons = compute_auto_modifiers(ch, gs, roll_kind="attack", label="выстрел из пистолета")
        assert dis is True
        assert any("погода:fog" in r for r in reasons)

    def test_fog_does_not_disadvantage_melee(self):
        ch = FakeCharacter()
        gs = FakeSession(weather="fog")
        _, dis, _ = compute_auto_modifiers(ch, gs, roll_kind="attack", label="удар мечом")
        assert dis is False

    def test_night_without_light_disadvantages_perception(self):
        ch = FakeCharacter()
        gs = FakeSession(time_of_day="night", has_light_source=False)
        _, dis, _ = compute_auto_modifiers(ch, gs, roll_kind="check", label="внимательность")
        assert dis is True

    def test_night_with_light_does_not_disadvantage(self):
        ch = FakeCharacter()
        gs = FakeSession(time_of_day="night", has_light_source=True)
        _, dis, _ = compute_auto_modifiers(ch, gs, roll_kind="check", label="внимательность")
        assert dis is False


class TestDamageTypes:
    def test_resistance_halves_damage(self):
        ch = FakeCharacter(hp_current=20, hp_max=20, resistances_json='{"resist":["fire"],"immune":[],"vulnerable":[]}')
        old, new = apply_damage(ch, -10, damage_type="fire")
        assert old == 20
        assert new == 15  # 10 // 2 = 5 damage applied

    def test_immunity_blocks_damage(self):
        ch = FakeCharacter(hp_current=20, hp_max=20, resistances_json='{"resist":[],"immune":["poison"],"vulnerable":[]}')
        _, new = apply_damage(ch, -15, damage_type="poison")
        assert new == 20

    def test_vulnerability_doubles(self):
        ch = FakeCharacter(hp_current=30, hp_max=30, resistances_json='{"resist":[],"immune":[],"vulnerable":["cold"]}')
        _, new = apply_damage(ch, -5, damage_type="cold")
        assert new == 20  # 5 * 2 = 10 damage

    def test_no_type_no_modification(self):
        ch = FakeCharacter(hp_current=20, hp_max=20, resistances_json='{"resist":["fire"]}')
        _, new = apply_damage(ch, -5, damage_type="")
        assert new == 15

    def test_healing_ignores_resistance(self):
        ch = FakeCharacter(hp_current=5, hp_max=20, resistances_json='{"resist":["fire"]}')
        _, new = apply_damage(ch, +10, damage_type="fire")
        assert new == 15


class TestDeathSaves:
    def test_success_on_high_roll(self, monkeypatch):
        import random as r
        monkeypatch.setattr(r, "randint", lambda a, b: 15)
        ch = FakeCharacter(hp_current=0)
        res = roll_death_save(ch)
        assert res.success is True
        assert ch.death_saves_success == 1
        assert ch.death_saves_failure == 0

    def test_fail_on_low_roll(self, monkeypatch):
        import random as r
        monkeypatch.setattr(r, "randint", lambda a, b: 5)
        ch = FakeCharacter(hp_current=0)
        res = roll_death_save(ch)
        assert res.success is False
        assert ch.death_saves_failure == 1

    def test_nat20_wakes_with_1hp(self, monkeypatch):
        import random as r
        monkeypatch.setattr(r, "randint", lambda a, b: 20)
        ch = FakeCharacter(hp_current=0)
        res = roll_death_save(ch)
        assert res.woke_up is True
        assert ch.hp_current == 1

    def test_nat1_counts_as_two_fails(self, monkeypatch):
        import random as r
        monkeypatch.setattr(r, "randint", lambda a, b: 1)
        ch = FakeCharacter(hp_current=0)
        roll_death_save(ch)
        assert ch.death_saves_failure == 2

    def test_three_fails_is_dead(self, monkeypatch):
        import random as r
        monkeypatch.setattr(r, "randint", lambda a, b: 5)
        ch = FakeCharacter(hp_current=0)
        for _ in range(3):
            res = roll_death_save(ch)
        assert res.dead is True

    def test_three_successes_stabilize(self, monkeypatch):
        import random as r
        monkeypatch.setattr(r, "randint", lambda a, b: 15)
        ch = FakeCharacter(hp_current=0)
        for _ in range(3):
            res = roll_death_save(ch)
        assert res.stabilized is True


class TestRest:
    def test_short_rest_consumes_hit_die_and_heals(self, monkeypatch):
        import random as r
        monkeypatch.setattr(r, "randint", lambda a, b: 6)
        ch = FakeCharacter(hp_current=5, hp_max=20, hit_dice_remaining=2, hit_dice_max=3)
        lines = perform_short_rest(ch)
        assert ch.hit_dice_remaining == 1
        assert ch.hp_current > 5
        assert any("Короткий отдых" in ln for ln in lines)

    def test_short_rest_without_hit_dice_noop(self):
        ch = FakeCharacter(hp_current=5, hp_max=20, hit_dice_remaining=0, hit_dice_max=3)
        perform_short_rest(ch)
        assert ch.hp_current == 5

    def test_long_rest_full_restore(self):
        ch = FakeCharacter(
            hp_current=2, hp_max=20, temp_hp=3,
            conditions_json='["poisoned","frightened"]',
            death_saves_failure=2,
            hit_dice_remaining=1, hit_dice_max=4,
        )
        perform_long_rest(ch)
        assert ch.hp_current == 20
        assert ch.temp_hp == 0
        assert ch.death_saves_failure == 0
        conds = json.loads(ch.conditions_json)
        assert "poisoned" not in conds
        assert "frightened" not in conds
        # Hit dice restored up to half max (max(1, 4//2) = 2) → 1+2=3
        assert ch.hit_dice_remaining == 3


class TestRollsWithAutoModifiers:
    def test_attack_roll_picks_up_blinded(self):
        # Blinded character rolling an attack should auto-apply disadvantage.
        ch = FakeCharacter(conditions_json='["blinded"]')
        gs = FakeSession()
        rr = make_attack_roll(ch, target_ac=10, label="удар", gs=gs)
        assert rr.disadvantage is True
        assert "blinded" in rr.reasons

    def test_skill_check_picks_up_poisoned(self):
        ch = FakeCharacter(conditions_json='["poisoned"]')
        gs = FakeSession()
        rr = make_skill_check(ch, "внимательность", dc=12, gs=gs)
        assert rr.disadvantage is True
