"""Smoke tests for critical game paths. Run with: python -m pytest tests/test_smoke.py -v"""
from __future__ import annotations

import json
import pytest

from bot.services.game_engine import (
    build_full_character,
    calculate_ac,
    distribute_stats,
    ensure_ammo,
    generate_starting_inventory,
    long_rest,
    merge_inventory,
    normalize_class_name,
    short_rest,
    skill_check,
    _resolve_skill_ability,
)
from bot.services.gemini import (
    CharacterProposal,
    MechanicsDecision,
    MissionProposal,
    _coerce_types,
    _make_example,
    _strip_code_fences,
)
from bot.utils.formatters import format_character_sheet, format_inventory, md_to_html, truncate_for_telegram


class FakeCharacter:
    """Minimal mock that behaves like bot.models.character.Character for testing."""

    def __init__(self):
        self.name = "TestHero"
        self.race = "Human"
        self.char_class = "Fighter"
        self.level = 1
        self.xp = 0
        self.strength = 10
        self.dexterity = 10
        self.constitution = 10
        self.intelligence = 10
        self.wisdom = 10
        self.charisma = 10
        self.max_hp = 10
        self.current_hp = 10
        self.armor_class = 10
        self.initiative_bonus = 0
        self.speed = 30
        self.proficiency_bonus = 2
        self.proficient_skills = []
        self.saving_throw_proficiencies = []
        self.gold = 0
        self._inventory_data = []
        self.backstory = ""
        self.conditions = []
        self.death_save_successes = 0
        self.death_save_failures = 0
        self.hit_dice_current = 1
        self.hit_dice_max = 1
        self.hit_dice_face = "d8"
        self.spell_slots_json = "{}"
        self._spell_slots = {}

    @property
    def inventory(self):
        return self._inventory_data

    @inventory.setter
    def inventory(self, value):
        self._inventory_data = value

    @property
    def spell_slots(self):
        return self._spell_slots

    @spell_slots.setter
    def spell_slots(self, value):
        self._spell_slots = value

    def ability_modifier(self, score):
        return (score - 10) // 2

    @property
    def str_mod(self):
        return self.ability_modifier(self.strength)
    @property
    def dex_mod(self):
        return self.ability_modifier(self.dexterity)
    @property
    def con_mod(self):
        return self.ability_modifier(self.constitution)
    @property
    def int_mod(self):
        return self.ability_modifier(self.intelligence)
    @property
    def wis_mod(self):
        return self.ability_modifier(self.wisdom)
    @property
    def cha_mod(self):
        return self.ability_modifier(self.charisma)


# --- normalize_class_name ---

@pytest.mark.parametrize("raw,expected", [
    ("Fighter", "Fighter"),
    ("Воин", "Fighter"),
    ("Плут", "Rogue"),
    ("маг", "Wizard"),
    ("ВАРВАР", "Barbarian"),
    ("Чернокнижник", "Warlock"),
    ("Друид", "Druid"),
    ("nonsense_class", "Fighter"),
])
def test_normalize_class_name(raw, expected):
    assert normalize_class_name(raw) == expected


# --- distribute_stats ---

def test_distribute_stats_fighter():
    stats = distribute_stats("Fighter")
    assert stats["strength"] == 15
    assert stats["constitution"] == 14
    assert len(stats) == 6
    assert set(stats.values()) == {15, 14, 13, 12, 10, 8}


def test_distribute_stats_unknown_defaults_to_fighter():
    stats = distribute_stats("UnknownClass")
    assert stats["strength"] == 15


# --- build_full_character ---

@pytest.mark.parametrize("cls", [
    "Fighter", "Wizard", "Rogue", "Cleric", "Ranger", "Paladin",
    "Bard", "Barbarian", "Monk", "Sorcerer", "Warlock", "Druid",
])
def test_build_full_character_all_classes(cls):
    char = FakeCharacter()
    build_full_character(
        char,
        char_class=cls,
        race="Elf",
        backstory="A test backstory.",
        proficient_skills=["Stealth", "Perception"],
        personality="Brave.",
    )
    assert char.char_class == cls
    assert char.max_hp > 0
    assert char.current_hp == char.max_hp
    assert char.armor_class >= 10
    assert len(char.inventory) > 0
    assert char.gold > 0
    assert char.proficiency_bonus == 2
    assert char.level == 1


def test_build_full_character_russian_class():
    char = FakeCharacter()
    build_full_character(char, char_class="Плут", race="Полуэльф")
    assert char.char_class == "Rogue"
    assert char.dexterity == 15


def test_build_full_character_empty_skills():
    char = FakeCharacter()
    build_full_character(char, char_class="Fighter", proficient_skills=None)
    assert char.proficient_skills == []


def test_build_full_character_too_many_skills():
    char = FakeCharacter()
    build_full_character(char, char_class="Fighter", proficient_skills=["a", "b", "c", "d", "e", "f"])
    assert len(char.proficient_skills) <= 4


# --- _resolve_skill_ability ---

def test_resolve_skill_english():
    assert _resolve_skill_ability("Stealth") == "dexterity"
    assert _resolve_skill_ability("Persuasion") == "charisma"


def test_resolve_skill_russian():
    assert _resolve_skill_ability("Убеждение") == "charisma"
    assert _resolve_skill_ability("Скрытность") == "dexterity"
    assert _resolve_skill_ability("Атлетика") == "strength"


def test_resolve_skill_case_insensitive():
    assert _resolve_skill_ability("stealth") == "dexterity"
    assert _resolve_skill_ability("STEALTH") == "dexterity"


def test_resolve_skill_unknown():
    assert _resolve_skill_ability("MadeUpSkill") == "wisdom"


# --- skill_check ---

def test_skill_check_russian_skill():
    char = FakeCharacter()
    char.dexterity = 16
    char.proficient_skills = ["Скрытность"]
    result = skill_check(char, "Скрытность", dc=10)
    assert result.skill_name == "Скрытность"


# --- calculate_ac ---

def test_calculate_ac_heavy_armor_plus_shield():
    char = FakeCharacter()
    char.dexterity = 8
    char.inventory = [
        {"name": "Chain Mail", "type": "armor", "mechanics": {"ac": 16, "type": "heavy"}, "equipped": True},
        {"name": "Shield", "type": "armor", "mechanics": {"ac": 2, "type": "shield"}, "equipped": True},
    ]
    assert calculate_ac(char) == 18


def test_calculate_ac_light_armor():
    char = FakeCharacter()
    char.dexterity = 16
    char.inventory = [
        {"name": "Leather Armor", "type": "armor", "mechanics": {"ac": 11, "type": "light"}, "equipped": True},
    ]
    assert calculate_ac(char) == 14  # 11 + 3 (dex mod)


def test_calculate_ac_no_armor():
    char = FakeCharacter()
    char.dexterity = 14
    char.inventory = []
    assert calculate_ac(char) == 12  # 10 + 2 (dex mod)


# --- rest ---

def test_long_rest_restores_hp():
    char = FakeCharacter()
    char.max_hp = 20
    char.current_hp = 5
    char.hit_dice_max = 3
    char.hit_dice_current = 0
    result = long_rest(char)
    assert char.current_hp == 20
    assert char.hit_dice_current >= 1
    assert "15" in result  # healed 15 HP


def test_long_rest_localized():
    char = FakeCharacter()
    char.max_hp = 10
    char.current_hp = 10
    result_ru = long_rest(char, lang="ru")
    assert "Длинный отдых" in result_ru
    result_en = long_rest(char, lang="en")
    assert "Long rest" in result_en


# --- merge_inventory ---

def test_merge_add():
    inv = [{"name": "Sword", "quantity": 1}]
    changes = [{"name": "Potion", "quantity": 2, "action": "add"}]
    result = merge_inventory(inv, changes)
    names = [i["name"] for i in result]
    assert "Potion" in names or "potion" in [n.lower() for n in names]


def test_merge_remove():
    inv = [{"name": "Sword", "quantity": 1}, {"name": "Potion", "quantity": 3}]
    changes = [{"name": "Sword", "action": "remove"}]
    result = merge_inventory(inv, changes)
    names = [i["name"].lower() for i in result]
    assert "sword" not in names


def test_merge_stack():
    inv = [{"name": "Arrow", "quantity": 10}]
    changes = [{"name": "Arrow", "quantity": 5, "action": "add"}]
    result = merge_inventory(inv, changes)
    arrow = [i for i in result if i["name"].lower() == "arrow"][0]
    assert arrow["quantity"] == 15


# --- ensure_ammo ---

def test_ensure_ammo_adds_ammo():
    inv = [{"name": "Shortbow", "type": "weapon", "quantity": 1}]
    result = ensure_ammo(inv)
    assert any(i.get("type") == "ammo" for i in result)


def test_ensure_ammo_no_duplicate():
    inv = [
        {"name": "Shortbow", "type": "weapon", "quantity": 1},
        {"name": "Arrows", "type": "ammo", "quantity": 20},
    ]
    result = ensure_ammo(inv)
    ammo_count = sum(1 for i in result if i.get("type") == "ammo")
    assert ammo_count == 1


# --- _coerce_types ---

def test_coerce_string_to_list():
    raw = {"proficient_skills": "['Stealth', 'Perception']"}
    result = _coerce_types(raw, CharacterProposal)
    assert isinstance(result["proficient_skills"], list)
    assert "Stealth" in result["proficient_skills"]


def test_coerce_string_to_list_comma():
    raw = {"proficient_skills": "Stealth, Perception"}
    result = _coerce_types(raw, CharacterProposal)
    assert isinstance(result["proficient_skills"], list)
    assert len(result["proficient_skills"]) == 2


def test_coerce_none_to_list():
    raw = {"proficient_skills": None}
    result = _coerce_types(raw, CharacterProposal)
    assert result["proficient_skills"] == []


def test_coerce_none_to_string():
    raw = {"backstory": None}
    result = _coerce_types(raw, CharacterProposal)
    assert result["backstory"] == ""


def test_coerce_none_to_int():
    raw = {"attack_target_ac": None}
    result = _coerce_types(raw, MechanicsDecision)
    assert result["attack_target_ac"] == 0


def test_coerce_float_to_int():
    raw = {"attack_target_ac": 15.0}
    result = _coerce_types(raw, MechanicsDecision)
    assert result["attack_target_ac"] == 15


def test_coerce_string_int():
    raw = {"attack_target_ac": "15"}
    result = _coerce_types(raw, MechanicsDecision)
    assert result["attack_target_ac"] == 15


# --- _strip_code_fences ---

def test_strip_code_fences_json():
    text = '```json\n{"name": "test"}\n```'
    assert _strip_code_fences(text) == '{"name": "test"}'


def test_strip_code_fences_plain():
    text = '{"name": "test"}'
    assert _strip_code_fences(text) == '{"name": "test"}'


# --- _make_example ---

def test_make_example_char_proposal():
    example = _make_example(CharacterProposal)
    parsed = json.loads(example)
    assert "name" in parsed
    assert "race" in parsed
    assert "char_class" in parsed
    assert "proficient_skills" in parsed
    assert "backstory" in parsed


def test_make_example_mission():
    example = _make_example(MissionProposal)
    parsed = json.loads(example)
    assert "quest_title" in parsed
    assert "opening_scene" in parsed


# --- md_to_html ---

def test_md_to_html_bold():
    assert md_to_html("**test**") == "<b>test</b>"


def test_md_to_html_italic():
    assert md_to_html("*test*") == "<i>test</i>"


def test_md_to_html_strips_unsupported_tags():
    assert md_to_html("<script>alert(1)</script>") == "alert(1)"
    assert md_to_html("<div>text</div>") == "text"


def test_md_to_html_keeps_allowed_tags():
    assert "<b>" in md_to_html("<b>bold</b>")
    assert "<i>" in md_to_html("<i>italic</i>")


def test_md_to_html_code_blocks():
    result = md_to_html("`code`")
    assert "<code>code</code>" == result


# --- truncate_for_telegram ---

def test_truncate_short():
    assert truncate_for_telegram("hello", 100) == "hello"


def test_truncate_closes_tags():
    long_text = "<b>" + "a" * 4000
    result = truncate_for_telegram(long_text, 100)
    assert result.endswith("</b>...")


# --- format_character_sheet ---

def test_format_character_sheet():
    char = FakeCharacter()
    build_full_character(char, "Fighter", "Human", "A warrior.", ["Athletics"], "Brave")
    sheet = format_character_sheet(char)
    assert "TestHero" in sheet
    assert "Fighter" in sheet
    assert "STR" in sheet
    assert "HP:" in sheet
    assert "AC:" in sheet


# --- format_inventory ---

def test_format_inventory_empty():
    char = FakeCharacter()
    char._inventory_data = []
    result = format_inventory(char)
    assert "Empty" in result or "empty" in result.lower()


def test_format_inventory_with_items():
    char = FakeCharacter()
    build_full_character(char, "Fighter")
    result = format_inventory(char)
    assert "Longsword" in result
    assert "Chain Mail" in result
    assert "Equipped" in result or "equipped" in result.lower()


# --- CharacterProposal validation ---

def test_character_proposal_defaults():
    p = CharacterProposal()
    assert p.race == "Human"
    assert p.char_class == "Fighter"
    assert p.proficient_skills == []


def test_character_proposal_from_dict():
    raw = {
        "name": "Тест",
        "race": "Эльф",
        "char_class": "Маг",
        "proficient_skills": ["Магия", "История"],
        "backstory": "Длинная предыстория...",
        "personality_summary": "Мудрый и задумчивый",
    }
    p = CharacterProposal.model_validate(raw)
    assert p.name == "Тест"
    assert len(p.proficient_skills) == 2
