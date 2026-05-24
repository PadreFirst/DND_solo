"""Tests for GameService — the core game logic orchestrator."""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from sqlalchemy import select

from bot.models import User
from bot.schemas import RollRequest, TurnPlan
from bot.services.game_service import GameService, TurnOutput, is_gm_question


@dataclass
class FakeGameSession:
    """Lightweight stand-in for GameSession ORM."""
    current_location: str = "Тестовая локация"
    current_location_description: str = "Тестовое описание"
    last_options_json: str = "[]"


class TestIsGmQuestion:
    """Verify that GM question detection uses strict prefix matching only."""

    def test_gm_prefix_russian(self):
        assert is_gm_question("ГМ: что такое проверка навыка?")

    def test_gm_prefix_english(self):
        assert is_gm_question("gm: how does advantage work?")

    def test_master_prefix(self):
        assert is_gm_question("мастер: объясни механику")

    def test_question_prefix(self):
        assert is_gm_question("вопрос: как работает инициатива?")

    def test_normal_text_not_gm(self):
        assert not is_gm_question("Атакую гоблина мечом")

    def test_contains_keywords_but_not_prefix(self):
        """Previously this was caught by 'что такое' substring match — fixed."""
        assert not is_gm_question("Спрашиваю NPC что такое этот артефакт")

    def test_contains_how_works_not_prefix(self):
        assert not is_gm_question("Попробую понять как работает этот механизм")

    def test_empty_string(self):
        assert not is_gm_question("")

    def test_none(self):
        assert not is_gm_question(None)


class TestEnsureOptions:
    def test_returns_up_to_5(self):
        opts = GameService._ensure_options(["a", "b", "c", "d", "e", "f"])
        assert len(opts) <= 5

    def test_appends_write_option(self):
        opts = GameService._ensure_options(["a", "b", "c"])
        assert any(o.startswith("✏") for o in opts)

    def test_too_few_options_uses_defaults(self):
        opts = GameService._ensure_options(["a"])
        assert len(opts) >= 3
        assert any(o.startswith("✏") for o in opts)

    def test_empty_input(self):
        opts = GameService._ensure_options([])
        assert len(opts) >= 3

    def test_already_has_write_option(self):
        opts = GameService._ensure_options(["a", "b", "c", "✏ Написать свой вариант"])
        count = sum(1 for o in opts if o.startswith("✏"))
        assert count == 1


class TestParseNumberedOptions:
    def test_standard_format(self):
        text = "Текст\n1) Осмотреть\n2) Поговорить\n3) Уйти\n4) Свой вариант"
        opts = GameService._parse_numbered_options(text)
        assert opts == ["Осмотреть", "Поговорить", "Уйти", "Свой вариант"]

    def test_no_options(self):
        text = "Просто текст без вариантов."
        opts = GameService._parse_numbered_options(text)
        assert opts == []

    def test_mixed_content(self):
        text = "Описание сцены.\nТаверна тёмная.\n1) Подойти\n2) Уйти"
        opts = GameService._parse_numbered_options(text)
        assert opts == ["Подойти", "Уйти"]

    def test_two_digit_numbers(self):
        text = "10) Десятый вариант"
        opts = GameService._parse_numbered_options(text)
        assert opts == ["Десятый вариант"]


class TestStripNumberedOptions:
    def test_removes_options(self):
        text = "Описание.\n1) Вариант\n2) Другой"
        result = GameService._strip_numbered_options(text)
        assert result == "Описание."

    def test_preserves_narrative(self):
        text = "Ты входишь.\nТаверна гудит."
        result = GameService._strip_numbered_options(text)
        assert result == text


class TestFallbackTurnPlan:
    def setup_method(self):
        self.gemini = AsyncMock()
        self.svc = GameService(self.gemini)
        self.gs = FakeGameSession()

    def test_attack_keywords(self):
        for word in ("атакую", "ударю", "бью", "стреляю"):
            plan = self.svc._fallback_turn_plan(word, self.gs)
            assert len(plan.rolls) >= 1
            assert plan.rolls[0].type == "attack"
            assert isinstance(plan.rolls[0], RollRequest)
            assert len(plan.enemy_actions) >= 1

    def test_potion_keywords(self):
        plan = self.svc._fallback_turn_plan("выпью зелье лечения", self.gs)
        assert plan.direct_hp_change > 0
        assert len(plan.inventory_changes) >= 1
        assert plan.inventory_changes[0].action == "use"

    def test_rest_keywords(self):
        plan = self.svc._fallback_turn_plan("короткий отдых", self.gs)
        assert plan.direct_hp_change > 0

    def test_inspect_keywords(self):
        plan = self.svc._fallback_turn_plan("осмотрю комнату", self.gs)
        assert len(plan.rolls) >= 1
        assert plan.rolls[0].type == "skill"

    def test_gm_question_fallback(self):
        plan = self.svc._fallback_turn_plan("ГМ: что такое КД?", self.gs)
        assert plan.gm_question_mode
        assert plan.gm_answer

    def test_generic_action(self):
        plan = self.svc._fallback_turn_plan("танцую на столе", self.gs)
        assert plan.narrative
        assert len(plan.options) >= 3

    def test_all_options_have_write_variant(self):
        plan = self.svc._fallback_turn_plan("что угодно", self.gs)
        assert any(o.startswith("✏") for o in plan.options)


@pytest.mark.asyncio
class TestInitializeStory:
    async def test_turn_number_incremented(self, db):
        gemini = AsyncMock()
        gemini.generate_world_opening = AsyncMock(return_value=TurnPlan(
            narrative="Ты входишь в таверну.",
            options=["Осмотреть", "Поговорить", "Уйти"],
        ))
        svc = GameService(gemini)
        user = User(telegram_id=111, username="tester")
        db.add(user)
        await db.flush()

        out = await svc.initialize_story(db, user, "эльф-маг")
        gs = await svc.ensure_session(db, user)
        assert gs.turn_number == 1, "turn_number must be 1 after initialization"

    async def test_options_from_structured_plan(self, db):
        gemini = AsyncMock()
        gemini.generate_world_opening = AsyncMock(return_value=TurnPlan(
            narrative="Сцена боя.",
            options=["Атаковать", "Бежать", "Поговорить"],
            location_name="Арена",
        ))
        svc = GameService(gemini)
        user = User(telegram_id=222, username="tester2")
        db.add(user)
        await db.flush()

        out = await svc.initialize_story(db, user, "воин")
        assert "Атаковать" in out.options
        assert "Бежать" in out.options

    async def test_location_updated_from_plan(self, db):
        gemini = AsyncMock()
        gemini.generate_world_opening = AsyncMock(return_value=TurnPlan(
            narrative="Ты видишь пещеру.",
            location_name="Тёмная пещера",
            location_description="Холодно и сыро.",
            quest_update="Исследовать пещеру.",
            options=["Войти", "Уйти", "Осмотреть вход"],
        ))
        svc = GameService(gemini)
        user = User(telegram_id=333, username="tester3")
        db.add(user)
        await db.flush()

        out = await svc.initialize_story(db, user, "дварф")
        assert "пещеру" in out.text
        gs = await svc.ensure_session(db, user)
        assert gs.current_location == "Тёмная пещера"
        assert gs.active_quest_summary == "Исследовать пещеру."

    async def test_fallback_on_gemini_error(self, db):
        gemini = AsyncMock()
        gemini.generate_world_opening = AsyncMock(side_effect=RuntimeError("API failed"))
        svc = GameService(gemini)
        user = User(telegram_id=444, username="tester4")
        db.add(user)
        await db.flush()

        out = await svc.initialize_story(db, user, "тифлинг-варлок")
        assert out.text
        assert len(out.options) >= 3
        gs = await svc.ensure_session(db, user)
        assert gs.turn_number == 1
        assert gs.current_location  # fallback sets location


@pytest.mark.asyncio
class TestProcessTurn:
    async def test_basic_turn(self, db):
        gemini = AsyncMock()
        gemini.generate_turn_plan = AsyncMock(
            return_value=TurnPlan(
                narrative="Ты осматриваешь комнату.",
                options=["Идти дальше", "Вернуться", "Осмотреть детали"],
            )
        )
        svc = GameService(gemini)
        user = User(telegram_id=555, username="player")
        db.add(user)
        await db.flush()

        gs = await svc.ensure_session(db, user)
        gs.turn_number = 1

        out = await svc.process_turn(db, user, "Осматриваю комнату")
        assert "осматриваешь" in out.text.lower()
        assert gs.turn_number == 2

    async def test_gm_question_does_not_lose_options(self, db):
        gemini = AsyncMock()
        gemini.generate_turn_plan = AsyncMock(
            return_value=TurnPlan(
                gm_question_mode=True,
                gm_answer="КД — это класс доспеха.",
                options=["Продолжить", "Другой вопрос"],
            )
        )
        svc = GameService(gemini)
        user = User(telegram_id=666, username="asker")
        db.add(user)
        await db.flush()

        gs = await svc.ensure_session(db, user)
        gs.turn_number = 1
        gs.last_options_json = json.dumps(["old1", "old2", "old3"])

        out = await svc.process_turn(db, user, "ГМ: что такое КД?")
        assert "КД" in out.text
        assert len(out.options) >= 2

    async def test_damage_and_enemy_attack(self, db):
        gemini = AsyncMock()
        gemini.generate_turn_plan = AsyncMock(
            return_value=TurnPlan(
                narrative="Бой начинается.",
                rolls=[RollRequest(type="attack", label="меч", ability="STR", dc=12)],
                enemy_actions=[],
                direct_hp_change=-3,
                options=["Атаковать", "Защититься", "Бежать"],
            )
        )
        svc = GameService(gemini)
        user = User(telegram_id=777, username="fighter")
        db.add(user)
        await db.flush()

        ch = await svc.ensure_character(db, user)
        old_hp = ch.hp_current
        gs = await svc.ensure_session(db, user)
        gs.turn_number = 1

        out = await svc.process_turn(db, user, "Атакую")
        assert ch.hp_current == old_hp - 3
        assert "HP" in out.text

    async def test_xp_and_levelup(self, db):
        gemini = AsyncMock()
        gemini.generate_turn_plan = AsyncMock(
            return_value=TurnPlan(
                narrative="Победа!",
                xp_award=300,
                options=["Дальше", "Отдых"],
            )
        )
        svc = GameService(gemini)
        user = User(telegram_id=888, username="hero")
        db.add(user)
        await db.flush()

        ch = await svc.ensure_character(db, user)
        gs = await svc.ensure_session(db, user)
        gs.turn_number = 1

        out = await svc.process_turn(db, user, "Добиваю")
        assert ch.level == 2
        assert "уровень" in out.text.lower()

    async def test_fallback_on_gemini_fail(self, db):
        gemini = AsyncMock()
        gemini.generate_turn_plan = AsyncMock(side_effect=RuntimeError("timeout"))
        svc = GameService(gemini)
        user = User(telegram_id=999, username="unlucky")
        db.add(user)
        await db.flush()

        gs = await svc.ensure_session(db, user)
        gs.turn_number = 1

        out = await svc.process_turn(db, user, "Атакую врага")
        assert out.text


class TestFormatStarterScreen:
    """Rich starter card shown ONCE after onboarding."""

    def _mk_char(self, **overrides):
        from bot.models import Character

        base = dict(
            user_id=1, name="Лютый Ёжик", race="Полуэльф", char_class="Бард",
            level=1, hp_current=9, hp_max=9, ac=13, speed_m=9, gold=15,
            abilities_json=json.dumps({"STR": 10, "DEX": 14, "CON": 12,
                                       "INT": 13, "WIS": 12, "CHA": 16}),
            inventory_json=json.dumps([
                {"name": "Рапира", "emoji": "🗡", "type": "weapon",
                 "is_equipped": True, "damage_dice": "1d8", "quantity": 1},
                {"name": "Зелье лечения", "emoji": "🧪",
                 "type": "consumable", "quantity": 2},
            ]),
            powers_json=json.dumps([
                {"name": "Вдохновение барда", "emoji": "🎵",
                 "description": "+1d6 союзнику", "max_uses": 3,
                 "current_uses": 3, "refresh": "long"},
            ]),
        )
        base.update(overrides)
        return Character(**base)

    def test_renders_all_sections(self):
        ch = self._mk_char()
        out = GameService.format_starter_screen(ch)
        assert "ТВОЙ ПЕРСОНАЖ" in out
        assert "ХАРАКТЕРИСТИКИ" in out
        assert "ЧТО ТЫ УМЕЕШЬ" in out
        assert "В РЮКЗАКЕ" in out
        assert "КАК ИГРАТЬ" in out
        # Russian stat names, no STR/DEX/CON/etc.
        assert "Сила" in out
        assert "Ловкость" in out
        assert "Харизма" in out
        assert "STR" not in out
        assert "DEX" not in out
        # Charges visible.
        assert "3/3" in out

    def test_skips_powers_section_if_empty(self):
        ch = self._mk_char(powers_json="[]")
        out = GameService.format_starter_screen(ch)
        assert "ЧТО ТЫ УМЕЕШЬ" not in out
        # But still has the rest.
        assert "ХАРАКТЕРИСТИКИ" in out
        assert "В РЮКЗАКЕ" in out

    def test_skips_inventory_section_if_empty(self):
        ch = self._mk_char(inventory_json="[]")
        out = GameService.format_starter_screen(ch)
        assert "В РЮКЗАКЕ" not in out


@pytest.mark.asyncio
class TestFailIsFail:
    """Failed rolls must not produce same-turn rewards (system_prompt #1)."""

    async def test_failed_skill_strips_xp_and_grants(self, db):
        from bot.schemas import (
            RollRequest, InventoryChange, Recipe, RecipeComponent, Ability,
            QuestEvent,
        )

        gemini = AsyncMock()
        gemini.generate_turn_plan = AsyncMock(return_value=TurnPlan(
            narrative="Ты пытаешься взломать дверь, но замок не поддаётся.",
            rolls=[RollRequest(type="skill", label="ловкость рук", ability="DEX", dc=99)],
            xp_award=50,
            inventory_changes=[InventoryChange(action="add", name="Хитрый ключ", quantity=1)],
            grant_recipe=Recipe(name="Отмычка", components=[RecipeComponent(name="Проволока", quantity=1)]),
            grant_ability=Ability(name="Внутренний взор", max_uses=1, current_uses=1),
            quest_events=[QuestEvent(action="complete", title="Открыть дверь")],
            options=["Попробовать снова", "Уйти"],
        ))
        svc = GameService(gemini)
        user = User(telegram_id=70001, username="fail_tester")
        db.add(user)
        await db.flush()
        ch = await svc.ensure_character(db, user)
        gs = await svc.ensure_session(db, user)
        gs.turn_number = 1
        xp_before = ch.xp_current

        await svc.process_turn(db, user, "взломать замок")
        # All same-turn rewards must be stripped because the DC=99 check failed.
        assert ch.xp_current == xp_before
        inv = json.loads(ch.inventory_json or "[]")
        assert not any(i.get("name") == "Хитрый ключ" for i in inv)
        recipes = json.loads(ch.known_recipes_json or "[]")
        assert not any(r.get("name") == "Отмычка" for r in recipes)
        powers = json.loads(ch.powers_json or "[]")
        assert not any(p.get("name") == "Внутренний взор" for p in powers)

    async def test_successful_skill_keeps_rewards(self, db):
        from bot.schemas import RollRequest, InventoryChange

        gemini = AsyncMock()
        gemini.generate_turn_plan = AsyncMock(return_value=TurnPlan(
            narrative="Ты легко вскрываешь дверь.",
            rolls=[RollRequest(type="skill", label="ловкость рук", ability="DEX", dc=1)],
            xp_award=25,
            inventory_changes=[InventoryChange(action="add", name="Письмо", quantity=1)],
            options=["Войти", "Подождать"],
        ))
        svc = GameService(gemini)
        user = User(telegram_id=70002, username="ok_tester")
        db.add(user)
        await db.flush()
        ch = await svc.ensure_character(db, user)
        gs = await svc.ensure_session(db, user)
        gs.turn_number = 1
        xp_before = ch.xp_current

        await svc.process_turn(db, user, "вскрываю")
        assert ch.xp_current == xp_before + 25
        inv = json.loads(ch.inventory_json or "[]")
        assert any(i.get("name") == "Письмо" for i in inv)


@pytest.mark.asyncio
class TestQuestCooldownAndMerge:
    """Quest spam protection (system_prompt #5)."""

    async def test_create_blocked_by_cooldown(self, db):
        from bot.schemas import QuestEvent

        gemini = AsyncMock()
        svc = GameService(gemini)
        user = User(telegram_id=70010, username="quest_tester")
        db.add(user)
        await db.flush()
        gs = await svc.ensure_session(db, user)
        gs.turn_number = 3
        gs.last_quest_create_turn = 2  # only 1 turn since last create

        await svc._apply_quest_event(db, user, QuestEvent(
            action="create", title="Второй квест за два хода",
        ))
        from bot.models import Quest
        rows = list(await db.scalars(select(Quest).where(Quest.user_id == user.id)))
        assert rows == []  # blocked

    async def test_similar_title_merges(self, db):
        from bot.schemas import QuestEvent
        from bot.models import Quest

        gemini = AsyncMock()
        svc = GameService(gemini)
        user = User(telegram_id=70011, username="merge_tester")
        db.add(user)
        await db.flush()
        gs = await svc.ensure_session(db, user)
        gs.turn_number = 10
        # First quest — straight create.
        await svc._apply_quest_event(db, user, QuestEvent(
            action="create", title="След крови сестры",
        ))
        gs.turn_number = 20  # past cooldown
        await svc._apply_quest_event(db, user, QuestEvent(
            action="create", title="По следам пропавшей сестры",
            description="Новые сведения о сестре",
        ))
        rows = list(await db.scalars(select(Quest).where(Quest.user_id == user.id)))
        assert len(rows) == 1  # merged, not duplicated
        assert "Новые сведения" in rows[0].description


@pytest.mark.asyncio
class TestNpcRegistry:
    async def test_appearance_persists(self, db):
        from bot.schemas import NPCAppearance
        from bot.models import NPCState, GameSession

        gemini = AsyncMock()
        svc = GameService(gemini)
        user = User(telegram_id=70020, username="npc_tester")
        db.add(user)
        await db.flush()
        gs = await svc.ensure_session(db, user)
        gs.turn_number = 5
        gs.current_location = "Бар Красный Дракон"

        await svc._upsert_npc_appearance(db, user, gs, NPCAppearance(
            name="Слай", role="информатор", faction="Синдикат",
            attitude="cold", notes="нервный, продаст за пол-цены",
        ))
        rows = list(await db.scalars(select(NPCState).where(NPCState.user_id == user.id)))
        assert len(rows) == 1
        assert rows[0].name == "Слай"
        assert rows[0].faction == "Синдикат"
        assert rows[0].last_seen_turn == 5

    async def test_appearance_idempotent_update(self, db):
        from bot.schemas import NPCAppearance
        from bot.models import NPCState

        gemini = AsyncMock()
        svc = GameService(gemini)
        user = User(telegram_id=70021, username="npc_tester2")
        db.add(user)
        await db.flush()
        gs = await svc.ensure_session(db, user)
        gs.turn_number = 5

        await svc._upsert_npc_appearance(db, user, gs, NPCAppearance(
            name="Слай", role="вор",
        ))
        gs.turn_number = 9
        await svc._upsert_npc_appearance(db, user, gs, NPCAppearance(
            name="Слай", role="вор", attitude="hostile",
            notes="теперь враг",
        ))
        rows = list(await db.scalars(select(NPCState).where(NPCState.user_id == user.id)))
        assert len(rows) == 1
        assert rows[0].attitude == "hostile"
        assert rows[0].last_seen_turn == 9


@pytest.mark.asyncio
class TestTensionClock:
    async def test_deadline_decrements_and_fails_at_zero(self, db):
        from bot.models import Quest, GameSession

        gemini = AsyncMock()
        svc = GameService(gemini)
        user = User(telegram_id=70030, username="clock_tester")
        db.add(user)
        await db.flush()
        gs = await svc.ensure_session(db, user)
        gs.turn_number = 5
        q = Quest(
            user_id=user.id, title="Спасти сестру", status="active",
            deadline_turns_remaining=2, last_updated_turn=1,
        )
        db.add(q)
        await db.flush()

        # Tick 1: 2 → 1, warning visible.
        lines = await svc._tick_quest_deadlines(db, user)
        assert any("Спасти сестру" in l for l in lines)
        assert q.status == "active"
        # Tick 2: 1 → 0, quest fails.
        lines = await svc._tick_quest_deadlines(db, user)
        assert q.status == "failed"
        assert any("Время вышло" in l for l in lines)


class TestOptionPrefixStripping:
    def test_strips_numbered_prefix(self):
        opts = GameService._ensure_options([
            "1. Атаковать", "2) Бежать", "- Спрятаться", "Поговорить",
        ])
        # The numbering prefix from the LLM must be gone (buttons already
        # display 1-5; double-numbering is visual noise).
        for label in opts[:4]:
            assert not label.startswith(("1.", "2.", "1)", "2)", "-"))
        assert "Атаковать" in opts
        assert "Бежать" in opts


@pytest.mark.asyncio
class TestBuildContextPreferences:
    """build_context must replay onboarding prefs into every turn."""

    async def test_prefs_inlined_into_context(self, db):
        from bot.models import GameSession

        gemini = AsyncMock()
        svc = GameService(gemini)
        user = User(telegram_id=12345, username="prefs_tester")
        db.add(user)
        await db.flush()
        ch = await svc.ensure_character(db, user)
        gs = await svc.ensure_session(db, user)
        gs.onboarding_state_json = json.dumps({
            "universe": "🌆 Киберпанк",
            "tone": "🌑 Тёмная и жёсткая",
            "rating": "18",
            "pace": "🚀 Быстрый",
            "difficulty": "💀 Хардкор",
        }, ensure_ascii=False)

        ctx = await svc.build_context(db, user, ch, gs)
        assert "PlayerPreferences" in ctx
        assert "Тёмная" in ctx
        assert "18+" in ctx
        assert "Быстрый" in ctx
        assert "Хардкор" in ctx

    async def test_no_prefs_section_when_state_empty(self, db):
        gemini = AsyncMock()
        svc = GameService(gemini)
        user = User(telegram_id=54321, username="no_prefs")
        db.add(user)
        await db.flush()
        ch = await svc.ensure_character(db, user)
        gs = await svc.ensure_session(db, user)

        ctx = await svc.build_context(db, user, ch, gs)
        assert "PlayerPreferences" not in ctx
