"""Tests for Batch D: abilities, level-up perks, quest events, companions."""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from bot.schemas import (
    Ability,
    CompanionSpec,
    LevelUpOffer,
    LevelUpPerk,
    QuestEvent,
    QuestStep,
)
from bot.services.engine import (
    add_power,
    consume_power_charge,
    find_power,
    format_powers,
    list_powers,
    perform_long_rest,
    perform_short_rest,
    refresh_powers,
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
    abilities_json: str = '{"STR":12,"DEX":14,"CON":13,"INT":10,"WIS":12,"CHA":10}'
    skill_proficiencies_json: str = '["внимательность"]'
    saving_throw_proficiencies_json: str = '["DEX","CON"]'
    conditions_json: str = "[]"
    resistances_json: str = '{"resist":[],"immune":[],"vulnerable":[]}'
    death_saves_success: int = 0
    death_saves_failure: int = 0
    hit_dice_remaining: int = 1
    hit_dice_max: int = 1
    inventory_json: str = "[]"
    known_recipes_json: str = "[]"
    attunement_json: str = '{"max":3,"items":[]}'
    powers_json: str = "[]"
    pending_level_ups: int = 0
    pending_levelup_offer_json: str = ""
    rest_status_json: str = '{"short_rest_used":false,"long_rest_available":true}'


# ─── Ability storage ─────────────────────────────────────────────────────

class TestAbilities:
    def test_empty_character_has_no_powers(self):
        ch = FakeCharacter()
        assert list_powers(ch) == []

    def test_add_power_ok(self):
        ch = FakeCharacter()
        added = add_power(ch, {
            "name": "Толчок Силы",
            "emoji": "✨",
            "description": "Отбросить цель ударной волной.",
            "max_uses": 3, "current_uses": 3, "refresh": "short",
            "damage_dice": "2d6", "damage_type": "force",
        })
        assert added is True
        powers = list_powers(ch)
        assert len(powers) == 1
        assert powers[0]["name"] == "Толчок Силы"
        assert powers[0]["current_uses"] == 3

    def test_add_duplicate_rejected(self):
        ch = FakeCharacter()
        add_power(ch, {"name": "Удар", "max_uses": 1, "current_uses": 1, "refresh": "long"})
        assert add_power(ch, {"name": "Удар", "max_uses": 2, "current_uses": 2, "refresh": "long"}) is False

    def test_consume_charge_reduces_uses(self):
        ch = FakeCharacter()
        add_power(ch, {"name": "Огненный шар", "max_uses": 2, "current_uses": 2, "refresh": "long"})
        ok, name = consume_power_charge(ch, "Огненный шар")
        assert ok is True
        assert name == "Огненный шар"
        powers = list_powers(ch)
        assert powers[0]["current_uses"] == 1

    def test_consume_partial_match(self):
        ch = FakeCharacter()
        add_power(ch, {"name": "Огненный шар", "max_uses": 1, "current_uses": 1, "refresh": "long"})
        ok, _ = consume_power_charge(ch, "огненный")
        assert ok is True

    def test_cannot_consume_when_empty(self):
        ch = FakeCharacter()
        add_power(ch, {"name": "Зов", "max_uses": 1, "current_uses": 0, "refresh": "long"})
        ok, reason = consume_power_charge(ch, "Зов")
        assert ok is False
        assert "заряды" in reason.lower()

    def test_at_will_never_runs_out(self):
        ch = FakeCharacter()
        add_power(ch, {"name": "Световой меч", "max_uses": 1, "current_uses": 1, "refresh": "at_will"})
        for _ in range(10):
            ok, _ = consume_power_charge(ch, "Световой меч")
            assert ok is True

    def test_unknown_power_returns_false(self):
        ch = FakeCharacter()
        ok, reason = consume_power_charge(ch, "Загадочный финт")
        assert ok is False
        assert "не найдена" in reason.lower()

    def test_find_power_case_insensitive(self):
        ch = FakeCharacter()
        add_power(ch, {"name": "Призыв духа", "max_uses": 1, "current_uses": 1, "refresh": "long"})
        assert find_power(ch, "ПРИЗЫВ ДУХА") is not None
        assert find_power(ch, "призыв") is not None
        assert find_power(ch, "шашки") is None

    def test_format_powers_empty(self):
        ch = FakeCharacter()
        text = format_powers(ch)
        assert "Способности" in text
        assert "Пока пусто" in text

    def test_format_powers_shows_charges_and_dice(self):
        ch = FakeCharacter()
        add_power(ch, {
            "name": "Молния", "emoji": "⚡",
            "max_uses": 2, "current_uses": 1, "refresh": "long",
            "damage_dice": "3d6", "damage_type": "lightning",
        })
        text = format_powers(ch)
        assert "Молния" in text
        assert "1/2" in text
        assert "3d6" in text


# ─── Refresh on rest ─────────────────────────────────────────────────────

class TestPowerRefresh:
    def test_short_rest_restores_short_but_not_long(self):
        ch = FakeCharacter(hit_dice_remaining=1, hit_dice_max=1)
        add_power(ch, {"name": "Маневр", "max_uses": 2, "current_uses": 0, "refresh": "short"})
        add_power(ch, {"name": "Мольба", "max_uses": 1, "current_uses": 0, "refresh": "long"})
        perform_short_rest(ch)
        powers = {p["name"]: p for p in list_powers(ch)}
        assert powers["Маневр"]["current_uses"] == 2
        assert powers["Мольба"]["current_uses"] == 0

    def test_long_rest_restores_everything(self):
        ch = FakeCharacter(hit_dice_remaining=1, hit_dice_max=1)
        add_power(ch, {"name": "Маневр", "max_uses": 2, "current_uses": 0, "refresh": "short"})
        add_power(ch, {"name": "Мольба", "max_uses": 1, "current_uses": 0, "refresh": "long"})
        add_power(ch, {"name": "Ярость", "max_uses": 3, "current_uses": 0, "refresh": "encounter"})
        perform_long_rest(ch)
        powers = {p["name"]: p for p in list_powers(ch)}
        assert powers["Маневр"]["current_uses"] == 2
        assert powers["Мольба"]["current_uses"] == 1
        assert powers["Ярость"]["current_uses"] == 3

    def test_encounter_refresh_only_encounter(self):
        ch = FakeCharacter()
        add_power(ch, {"name": "Ярость", "max_uses": 3, "current_uses": 0, "refresh": "encounter"})
        add_power(ch, {"name": "Мольба", "max_uses": 1, "current_uses": 0, "refresh": "long"})
        lines = refresh_powers(ch, "encounter")
        powers = {p["name"]: p for p in list_powers(ch)}
        assert powers["Ярость"]["current_uses"] == 3
        assert powers["Мольба"]["current_uses"] == 0
        assert any("Ярость" in ln for ln in lines)


# ─── Level-up offer & perks ──────────────────────────────────────────────

class TestLevelUpOffer:
    def test_offer_with_three_perks_parses(self):
        offer = LevelUpOffer(
            new_level=2, flavor="Сила пробуждается.",
            perks=[
                LevelUpPerk(id="p1", label="+1 Лов", effect_type="stat", stat_key="DEX", stat_delta=1),
                LevelUpPerk(id="p2", label="+4 HP", effect_type="hp", hp_delta=4),
                LevelUpPerk(id="p3", label="Молния", effect_type="ability",
                            granted_ability=Ability(name="Молния", max_uses=1, current_uses=1, refresh="long")),
            ],
        )
        assert offer.new_level == 2
        assert len(offer.perks) == 3
        assert offer.perks[2].granted_ability.name == "Молния"

    def test_stat_perk_defaults(self):
        perk = LevelUpPerk(id="x", label="Сил", effect_type="stat", stat_key="STR", stat_delta=1)
        assert perk.hp_delta == 0
        assert perk.granted_ability is None


# ─── Quest event schema ──────────────────────────────────────────────────

class TestQuestEventSchema:
    def test_create_event_with_steps(self):
        ev = QuestEvent(
            action="create", title="Найти сестру",
            description="Она пропала в старом районе.",
            is_main=True,
            steps=[QuestStep(key="ask", description="Расспросить в баре")],
            reward_xp=100, reward_gold=50,
        )
        assert ev.action == "create"
        assert ev.is_main is True
        assert ev.steps[0].done is False

    def test_complete_step_shape(self):
        ev = QuestEvent(action="complete_step", title="Найти сестру", step_key_completed="ask")
        assert ev.step_key_completed == "ask"


# ─── Companion schema ────────────────────────────────────────────────────

class TestCompanionSchema:
    def test_companion_with_defaults(self):
        c = CompanionSpec(name="R2-D8", role="дроид", hp_max=18, hp_current=18)
        assert c.ac == 12
        assert c.attack_bonus == 3
        assert c.damage_dice == "1d6"
