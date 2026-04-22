"""Tests for the dice rolling engine."""
from __future__ import annotations

import pytest

from bot.services.dice import RollResult, roll_dice


class TestRollDice:
    def test_basic_d20(self):
        result = roll_dice("1d20")
        assert isinstance(result, RollResult)
        assert 1 <= result.total <= 20

    def test_d20_with_modifier(self):
        result = roll_dice("1d20+5")
        assert 6 <= result.total <= 25
        assert "+5" in result.detail or result.detail.endswith("5")

    def test_d20_negative_modifier(self):
        result = roll_dice("1d20-2")
        assert -1 <= result.total <= 18

    def test_multiple_dice(self):
        result = roll_dice("2d6")
        assert 2 <= result.total <= 12

    def test_multiple_dice_with_modifier(self):
        result = roll_dice("3d8+4")
        assert 7 <= result.total <= 28

    def test_advantage(self):
        for _ in range(20):
            result = roll_dice("1d20+3", advantage=True)
            assert 4 <= result.total <= 23
            assert result.d20_first is not None
            assert result.d20_second is not None

    def test_disadvantage(self):
        for _ in range(20):
            result = roll_dice("1d20+3", disadvantage=True)
            assert 4 <= result.total <= 23

    def test_advantage_and_disadvantage_cancel(self):
        for _ in range(20):
            result = roll_dice("1d20", advantage=True, disadvantage=True)
            assert 1 <= result.total <= 20
            assert not result.used_advantage
            assert not result.used_disadvantage

    def test_invalid_expression_raises(self):
        with pytest.raises(ValueError, match="Invalid dice expression"):
            roll_dice("banana")

    def test_invalid_empty_raises(self):
        with pytest.raises(ValueError):
            roll_dice("")

    def test_1d1(self):
        result = roll_dice("1d1")
        assert result.total == 1

    def test_advantage_non_d20_ignored(self):
        result = roll_dice("2d6+1", advantage=True)
        assert 3 <= result.total <= 13
        assert result.d20_first is None
