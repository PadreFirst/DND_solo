"""Tests for Pydantic schemas and validation."""
from __future__ import annotations

import json

import pytest

from bot.schemas import EnemyAction, InventoryChange, RollRequest, TurnPlan


class TestTurnPlanValidation:
    def test_empty_plan(self):
        plan = TurnPlan()
        assert plan.narrative == ""
        assert plan.options == []
        assert plan.rolls == []

    def test_full_plan_from_dict(self):
        raw = {
            "narrative": "Ты входишь в пещеру.",
            "rolls": [{"type": "skill", "label": "внимательность", "ability": "WIS", "dc": 14}],
            "enemy_actions": [{"name": "Гоблин", "attack_bonus": 4, "damage_dice": "1d6+2"}],
            "options": ["Идти дальше", "Вернуться", "Осмотреться"],
            "xp_award": 50,
            "location_name": "Тёмная пещера",
        }
        plan = TurnPlan.model_validate(raw)
        assert plan.narrative == "Ты входишь в пещеру."
        assert len(plan.rolls) == 1
        assert isinstance(plan.rolls[0], RollRequest)
        assert plan.rolls[0].ability == "WIS"
        assert len(plan.enemy_actions) == 1
        assert isinstance(plan.enemy_actions[0], EnemyAction)
        assert plan.xp_award == 50

    def test_dict_coercion_in_constructor(self):
        """Verify that dicts passed to constructor are coerced into models."""
        plan = TurnPlan(
            narrative="test",
            rolls=[{"type": "attack", "label": "удар", "ability": "STR", "dc": 12}],
            enemy_actions=[{"name": "Враг", "attack_bonus": 3, "damage_dice": "1d6"}],
            inventory_changes=[{"action": "use", "name": "Зелье", "quantity": 1}],
        )
        assert isinstance(plan.rolls[0], RollRequest)
        assert isinstance(plan.enemy_actions[0], EnemyAction)
        assert isinstance(plan.inventory_changes[0], InventoryChange)

    def test_gm_question_mode(self):
        plan = TurnPlan(
            gm_question_mode=True,
            gm_answer="Отвечу на вопрос.",
            options=["Ок", "Понятно"],
        )
        assert plan.gm_question_mode
        assert plan.gm_answer == "Отвечу на вопрос."

    def test_model_validate_from_json_string(self):
        raw_json = json.dumps({
            "narrative": "Сцена",
            "options": ["a", "b", "c"],
        })
        plan = TurnPlan.model_validate_json(raw_json)
        assert plan.narrative == "Сцена"

    def test_invalid_roll_type_still_parses(self):
        plan = TurnPlan(rolls=[{"type": "unknown", "label": "test"}])
        assert plan.rolls[0].type == "unknown"
