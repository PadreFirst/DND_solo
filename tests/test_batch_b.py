"""Tests for Batch B: combat state machine, trading, crafting."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from bot.services.engine import (
    advance_round,
    attempt_craft,
    end_combat,
    format_combat_status,
    reset_action_economy,
    start_combat,
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
    abilities_json: str = '{"STR":14,"DEX":16,"CON":13,"INT":10,"WIS":12,"CHA":8}'
    skill_proficiencies_json: str = '["ловкость рук","медицина"]'
    saving_throw_proficiencies_json: str = '["DEX","CON"]'
    conditions_json: str = "[]"
    resistances_json: str = '{"resist":[],"immune":[],"vulnerable":[]}'
    death_saves_success: int = 0
    death_saves_failure: int = 0
    hit_dice_remaining: int = 1
    hit_dice_max: int = 1
    inventory_json: str = "[]"
    known_recipes_json: str = "[]"


@dataclass
class FakeSession:
    weather: str = "clear"
    time_of_day: str = "day"
    has_light_source: bool = True
    combat_active: bool = False
    round_number: int = 0
    current_turn_index: int = 0
    initiative_order_json: str = "[]"
    action_used: bool = False
    bonus_used: bool = False
    reaction_used: bool = False
    movement_remaining: int = 9


# ─── Combat state machine ─────────────────────────────────────────────────

class TestCombatStateMachine:
    def test_start_combat_rolls_initiative_for_all(self):
        gs = FakeSession()
        ch = FakeCharacter()
        scene = [
            {"name": "Громила", "hp_current": 10, "hp_max": 10, "ac": 12},
            {"name": "Снайпер", "hp_current": 6, "hp_max": 6, "ac": 11},
        ]
        order = start_combat(gs, ch, scene)
        assert gs.combat_active is True
        assert gs.round_number == 1
        assert len(order) == 3  # player + 2 enemies
        assert all("init" in o for o in order)
        # Sorted descending by init
        inits = [o["init"] for o in order]
        assert inits == sorted(inits, reverse=True)
        # Player present and labeled
        assert any(o["is_player"] for o in order)

    def test_start_combat_skips_dead_enemies(self):
        gs = FakeSession()
        ch = FakeCharacter()
        scene = [
            {"name": "Громила", "hp_current": 0, "hp_max": 10, "ac": 12},
            {"name": "Снайпер", "hp_current": 6, "hp_max": 6, "ac": 11},
        ]
        order = start_combat(gs, ch, scene)
        assert len(order) == 2  # player + 1 live enemy

    def test_start_combat_resets_action_economy(self):
        gs = FakeSession(action_used=True, bonus_used=True, reaction_used=True, movement_remaining=0)
        ch = FakeCharacter(speed_m=9)
        start_combat(gs, ch, [{"name": "X", "hp_current": 5, "hp_max": 5, "ac": 10}])
        assert gs.action_used is False
        assert gs.bonus_used is False
        assert gs.reaction_used is False
        assert gs.movement_remaining == 9

    def test_advance_round_increments_and_resets(self):
        gs = FakeSession(combat_active=True, round_number=1, action_used=True, bonus_used=True)
        ch = FakeCharacter(speed_m=9)
        advance_round(gs, ch)
        assert gs.round_number == 2
        assert gs.action_used is False
        assert gs.bonus_used is False
        assert gs.movement_remaining == 9

    def test_advance_round_noop_outside_combat(self):
        gs = FakeSession(combat_active=False, round_number=0)
        ch = FakeCharacter()
        advance_round(gs, ch)
        assert gs.round_number == 0

    def test_end_combat_wipes_state(self):
        gs = FakeSession(combat_active=True, round_number=3,
                         initiative_order_json='[{"name":"X","init":10}]',
                         action_used=True)
        end_combat(gs)
        assert gs.combat_active is False
        assert gs.round_number == 0
        assert gs.initiative_order_json == "[]"
        assert gs.action_used is False

    def test_format_combat_status_shows_round_and_economy(self):
        gs = FakeSession(combat_active=True, round_number=2,
                         initiative_order_json='[{"name":"Герой","init":18},{"name":"Громила","init":12}]',
                         action_used=False, bonus_used=True, reaction_used=False,
                         movement_remaining=6)
        text = format_combat_status(gs)
        assert "Раунд 2" in text
        assert "Герой(18)" in text
        assert "Громила(12)" in text
        assert "6м" in text
        # action available, bonus used → should include "действие" but not "бонус"
        assert "действие" in text
        assert "реакция" in text

    def test_reset_action_economy_sets_full_budget(self):
        gs = FakeSession(action_used=True, bonus_used=True, reaction_used=True, movement_remaining=0)
        ch = FakeCharacter(speed_m=12)
        reset_action_economy(gs, ch)
        assert gs.action_used is False
        assert gs.movement_remaining == 12


# ─── Crafting ─────────────────────────────────────────────────────────────

class TestCrafting:
    def _recipe(self) -> dict:
        return {
            "name": "Аптечка",
            "result_name": "Аптечка",
            "result_emoji": "🧰",
            "result_type": "consumable",
            "result_quantity": 1,
            "components": [
                {"name": "Бинт", "quantity": 2},
                {"name": "Антисептик", "quantity": 1},
            ],
            "skill": "медицина",
            "dc": 1,  # almost guaranteed success
        }

    def test_craft_missing_components_returns_missing_list(self):
        ch = FakeCharacter(inventory_json='[{"name":"Бинт","quantity":1,"emoji":"•","type":"misc"}]')
        result = attempt_craft(ch, self._recipe())
        assert result.success is False
        assert result.missing  # non-empty
        assert any("Антисептик" in m for m in result.missing)

    def test_craft_success_consumes_and_produces(self):
        ch = FakeCharacter(
            inventory_json=json.dumps([
                {"name": "Бинт", "quantity": 3, "emoji": "🩹", "type": "misc"},
                {"name": "Антисептик", "quantity": 2, "emoji": "🧴", "type": "misc"},
            ]),
        )
        result = attempt_craft(ch, self._recipe())
        # DC 1 → always succeeds
        assert result.success is True
        assert result.produced_name == "Аптечка"
        inv = json.loads(ch.inventory_json)
        # Components should be consumed (3-2=1, 2-1=1)
        names = {it["name"]: it["quantity"] for it in inv}
        assert names.get("Бинт") == 1
        assert names.get("Антисептик") == 1
        assert names.get("Аптечка") == 1

    def test_craft_failure_still_wastes_half_components(self):
        recipe = self._recipe()
        recipe["dc"] = 99  # impossible
        ch = FakeCharacter(
            inventory_json=json.dumps([
                {"name": "Бинт", "quantity": 4, "emoji": "🩹", "type": "misc"},
                {"name": "Антисептик", "quantity": 2, "emoji": "🧴", "type": "misc"},
            ]),
        )
        result = attempt_craft(ch, recipe)
        assert result.success is False
        inv = json.loads(ch.inventory_json)
        names = {it["name"]: it["quantity"] for it in inv}
        # Half of 2 bandages consumed (=1), half of 1 antiseptic consumed (=1)
        assert names.get("Бинт") == 4 - 1
        assert names.get("Антисептик") == 2 - 1
        assert "Аптечка" not in names

    def test_craft_stacks_into_existing_slot(self):
        recipe = self._recipe()
        ch = FakeCharacter(
            inventory_json=json.dumps([
                {"name": "Бинт", "quantity": 2, "emoji": "🩹", "type": "misc"},
                {"name": "Антисептик", "quantity": 1, "emoji": "🧴", "type": "misc"},
                {"name": "Аптечка", "quantity": 1, "emoji": "🧰", "type": "consumable"},
            ]),
        )
        attempt_craft(ch, recipe)
        inv = json.loads(ch.inventory_json)
        aptechka = next((it for it in inv if it["name"] == "Аптечка"), None)
        assert aptechka is not None
        assert aptechka["quantity"] == 2

    def test_craft_roll_line_is_populated(self):
        ch = FakeCharacter(
            inventory_json=json.dumps([
                {"name": "Бинт", "quantity": 2, "emoji": "🩹", "type": "misc"},
                {"name": "Антисептик", "quantity": 1, "emoji": "🧴", "type": "misc"},
            ]),
        )
        result = attempt_craft(ch, self._recipe())
        assert "Крафт" in result.roll_line
        assert "d20" in result.roll_line


# ─── Trading (service-level) ─────────────────────────────────────────────
#
# Trading involves the DB via NPCState, so it's tested at the service layer
# in an async session. Kept minimal — we already rely on SQLAlchemy tests
# in test_bot.py.

class TestTradingLogic:
    """Pure-logic checks that don't need the DB."""

    def test_trade_offer_schema_accepts_full_payload(self):
        from bot.schemas import TradeItem, TradeOffer
        offer = TradeOffer(
            npc="Риз",
            items=[TradeItem(name="Пистолет", emoji="🔫", item_type="ranged",
                             damage_dice="1d10", price=120, quantity=1)],
            buys_from_player=True,
            buy_back_rate=0.4,
        )
        assert offer.npc == "Риз"
        assert offer.items[0].damage_dice == "1d10"
        assert offer.buy_back_rate == 0.4

    def test_recipe_schema_defaults(self):
        from bot.schemas import Recipe, RecipeComponent
        r = Recipe(
            name="Бомба",
            result_name="Граната",
            result_emoji="💣",
            result_type="consumable",
            components=[RecipeComponent(name="Порох", quantity=1)],
        )
        assert r.dc == 12
        assert r.skill == "ловкость рук"
