"""End-to-end gameplay simulation — tests a full session without real Gemini calls."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from bot.models import User
from bot.schemas import EnemyAction, InventoryChange, RollRequest, TurnPlan
from bot.services.game_service import GameService


@pytest.mark.asyncio
class TestFullGameplaySession:
    """Simulate a multi-turn game session with mocked Gemini responses."""

    async def test_full_session(self, db):
        gemini = AsyncMock()
        svc = GameService(gemini)

        # --- Step 1: /start → user sends character concept ---
        user = User(telegram_id=10001, username="simulated_player")
        db.add(user)
        await db.flush()

        gs = await svc.ensure_session(db, user)
        assert gs.turn_number == 0, "Fresh session starts at turn 0"

        # --- Step 2: Initialize story ---
        gemini.generate_world_opening = AsyncMock(return_value=TurnPlan(
            narrative=(
                "Ты — Кайл, полуэльф-следопыт, стоишь на пороге заброшенной таверны. "
                "Внутри пахнет сыростью и чем-то сладковатым. За стойкой — фигура в капюшоне. "
                "Снаружи накрапывает дождь, и ветер доносит далёкий вой."
            ),
            location_name="Заброшенная таверна",
            location_description="Ветхое здание на окраине леса. Запах сырости и плесени.",
            quest_update="Узнать, кто скрывается за стойкой.",
            options=[
                "Подойти к фигуре в капюшоне",
                "Осмотреть таверну",
                "Проверить свой инвентарь",
                "Выйти наружу",
            ],
        ))
        out = await svc.initialize_story(db, user, "полуэльф следопыт в мрачном фэнтези мире")

        assert gs.turn_number == 1
        assert "Кайл" in out.text
        assert "Подойти к фигуре" in out.options[0]
        assert len(out.options) >= 4

        # --- Step 3: Player chooses option 1 (approach the figure) ---
        gemini.generate_turn_plan = AsyncMock(return_value=TurnPlan(
            narrative="Ты подходишь к фигуре. Она поднимает голову — старик с шрамом через всё лицо.",
            rolls=[RollRequest(type="skill", label="проницательность", ability="WIS", dc=12)],
            location_description="Заброшенная таверна. Пыль, паутина, разбитые бутылки.",
            options=["Спросить о руинах", "Предложить сделку", "Напасть", "Уйти"],
        ))
        out = await svc.process_turn(db, user, "Подойти к фигуре в капюшоне")

        assert gs.turn_number == 2
        assert "старик" in out.text.lower()
        # Dice / preview block — 🎲 normal roll, 💥 nat20, 💀 nat1, or 🎯 pre-roll preview.
        assert any(m in out.text for m in ("🎲", "💥", "💀", "🎯"))
        assert "проницательность" in out.text.lower()

        # --- Step 4: Player asks a question ---
        gemini.generate_turn_plan = AsyncMock(return_value=TurnPlan(
            gm_question_mode=True,
            gm_answer="Проницательность — это навык, позволяющий определить истинные намерения NPC. "
                       "Бросок: d20 + модификатор Мудрости + бонус владения (если есть).",
            options=["Спросить о руинах", "Предложить сделку", "Напасть", "Уйти"],
        ))
        out = await svc.process_turn(db, user, "ГМ: что такое проницательность?")

        assert "💡" in out.text
        assert "Проницательность" in out.text
        assert gs.turn_number == 3  # turn increments even for GM questions

        # --- Step 5: Combat scenario ---
        ch = await svc.ensure_character(db, user)
        old_hp = ch.hp_current

        gemini.generate_turn_plan = AsyncMock(return_value=TurnPlan(
            narrative="Старик внезапно выхватывает нож! Бой начинается!",
            rolls=[RollRequest(type="attack", label="удар мечом", ability="DEX", dc=14)],
            enemy_actions=[EnemyAction(name="Старик с ножом", attack_bonus=3, damage_dice="1d4+1", reason="нападение")],
            options=["Контратаковать", "Отступить", "Использовать зелье", "Попытаться обезоружить"],
        ))
        out = await svc.process_turn(db, user, "Напасть")

        assert gs.turn_number == 4
        assert "Бой" in out.text or "бой" in out.text or "нож" in out.text
        # Dice / preview block — 🎲 normal roll, 💥 nat20, 💀 nat1, or 🎯 pre-roll preview.
        assert any(m in out.text for m in ("🎲", "💥", "💀", "🎯"))

        # --- Step 6: Use healing potion ---
        gemini.generate_turn_plan = AsyncMock(return_value=TurnPlan(
            narrative="Ты быстро выпиваешь зелье лечения, чувствуя, как раны затягиваются.",
            direct_hp_change=7,
            inventory_changes=[InventoryChange(action="use", name="Зелье лечения", quantity=1)],
            options=["Атаковать старика", "Бежать", "Осмотреться"],
        ))
        hp_before = ch.hp_current
        out = await svc.process_turn(db, user, "Использую зелье лечения")

        assert gs.turn_number == 5
        assert "HP" in out.text
        assert "Использовано" in out.text
        assert ch.hp_current == min(ch.hp_max, hp_before + 7)

        # --- Step 7: Earn XP and level up ---
        gemini.generate_turn_plan = AsyncMock(return_value=TurnPlan(
            narrative="Ты побеждаешь старика. Он падает без сознания.",
            xp_award=350,
            options=["Обыскать старика", "Осмотреть таверну", "Покинуть таверну"],
        ))
        out = await svc.process_turn(db, user, "Добиваю врага")

        assert gs.turn_number == 6
        assert ch.level == 2
        assert "уровень" in out.text.lower()
        assert "XP" in out.text

    async def test_fallback_chain_no_gemini(self, db):
        """Full session using only fallback logic (Gemini always fails)."""
        gemini = AsyncMock()
        gemini.generate_world_opening = AsyncMock(side_effect=RuntimeError("API down"))
        gemini.generate_turn_plan = AsyncMock(side_effect=RuntimeError("API down"))
        svc = GameService(gemini)

        user = User(telegram_id=20001, username="offline_player")
        db.add(user)
        await db.flush()

        out = await svc.initialize_story(db, user, "воин в замке")
        gs = await svc.ensure_session(db, user)
        assert gs.turn_number == 1
        assert out.text
        assert len(out.options) >= 3

        out = await svc.process_turn(db, user, "Осмотрю зал")
        assert out.text
        assert "🎲" in out.text  # fallback triggers skill check for "осмотр"

        out = await svc.process_turn(db, user, "Атакую гоблина")
        assert out.text
        assert "🎲" in out.text  # fallback triggers attack roll

        out = await svc.process_turn(db, user, "Выпью зелье")
        assert out.text
        assert "HP" in out.text  # fallback triggers potion use

        out = await svc.process_turn(db, user, "ГМ: что такое КД?")
        assert "💡" in out.text  # fallback GM answer

        out = await svc.process_turn(db, user, "Просто иду вперед")
        assert out.text  # generic fallback

    async def test_new_game_resets_state(self, db):
        """Verify that resetting turn_number to 0 allows re-initialization."""
        gemini = AsyncMock()
        gemini.generate_world_opening = AsyncMock(return_value=TurnPlan(
            narrative="Новая история.", options=["Вперед", "Назад", "Стоять"],
        ))
        svc = GameService(gemini)

        user = User(telegram_id=30001, username="restarter")
        db.add(user)
        await db.flush()

        out = await svc.initialize_story(db, user, "маг")
        gs = await svc.ensure_session(db, user)
        assert gs.turn_number == 1

        gs.turn_number = 0
        gs.last_options_json = "[]"

        gemini.generate_world_opening = AsyncMock(return_value=TurnPlan(
            narrative="Другая история.", options=["Лево", "Право", "Центр"],
        ))
        out = await svc.initialize_story(db, user, "лучник")
        assert gs.turn_number == 1
        assert "Другая" in out.text
