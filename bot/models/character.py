from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    name: Mapped[str] = mapped_column(String(100), default="Unnamed")
    race: Mapped[str] = mapped_column(String(50), default="Human")
    char_class: Mapped[str] = mapped_column(String(50), default="Fighter")
    level: Mapped[int] = mapped_column(default=1)
    xp: Mapped[int] = mapped_column(default=0)

    strength: Mapped[int] = mapped_column(default=10)
    dexterity: Mapped[int] = mapped_column(default=10)
    constitution: Mapped[int] = mapped_column(default=10)
    intelligence: Mapped[int] = mapped_column(default=10)
    wisdom: Mapped[int] = mapped_column(default=10)
    charisma: Mapped[int] = mapped_column(default=10)

    max_hp: Mapped[int] = mapped_column(default=10)
    current_hp: Mapped[int] = mapped_column(default=10)
    armor_class: Mapped[int] = mapped_column(default=10)
    initiative_bonus: Mapped[int] = mapped_column(default=0)
    speed: Mapped[int] = mapped_column(default=30)

    proficiency_bonus: Mapped[int] = mapped_column(default=2)
    _proficient_skills: Mapped[str] = mapped_column(
        "proficient_skills", Text, default="[]"
    )
    _saving_throw_proficiencies: Mapped[str] = mapped_column(
        "saving_throw_proficiencies", Text, default="[]"
    )

    gold: Mapped[int] = mapped_column(default=0)
    _inventory: Mapped[str] = mapped_column("inventory", Text, default="[]")

    backstory: Mapped[str] = mapped_column(Text, default="")
    _conditions: Mapped[str] = mapped_column("conditions", Text, default="[]")

    death_save_successes: Mapped[int] = mapped_column(default=0)
    death_save_failures: Mapped[int] = mapped_column(default=0)

    spell_slots_json: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="character")

    # --- JSON property helpers ---

    @property
    def inventory(self) -> list[dict]:
        return json.loads(self._inventory)

    @inventory.setter
    def inventory(self, value: list[dict]) -> None:
        self._inventory = json.dumps(value, ensure_ascii=False)

    @property
    def proficient_skills(self) -> list[str]:
        return json.loads(self._proficient_skills)

    @proficient_skills.setter
    def proficient_skills(self, value: list[str]) -> None:
        self._proficient_skills = json.dumps(value, ensure_ascii=False)

    @property
    def saving_throw_proficiencies(self) -> list[str]:
        return json.loads(self._saving_throw_proficiencies)

    @saving_throw_proficiencies.setter
    def saving_throw_proficiencies(self, value: list[str]) -> None:
        self._saving_throw_proficiencies = json.dumps(value, ensure_ascii=False)

    @property
    def conditions(self) -> list[str]:
        return json.loads(self._conditions)

    @conditions.setter
    def conditions(self, value: list[str]) -> None:
        self._conditions = json.dumps(value, ensure_ascii=False)

    @property
    def spell_slots(self) -> dict:
        return json.loads(self.spell_slots_json)

    @spell_slots.setter
    def spell_slots(self, value: dict) -> None:
        self.spell_slots_json = json.dumps(value)

    def ability_modifier(self, score: int) -> int:
        return (score - 10) // 2

    @property
    def str_mod(self) -> int:
        return self.ability_modifier(self.strength)

    @property
    def dex_mod(self) -> int:
        return self.ability_modifier(self.dexterity)

    @property
    def con_mod(self) -> int:
        return self.ability_modifier(self.constitution)

    @property
    def int_mod(self) -> int:
        return self.ability_modifier(self.intelligence)

    @property
    def wis_mod(self) -> int:
        return self.ability_modifier(self.wisdom)

    @property
    def cha_mod(self) -> int:
        return self.ability_modifier(self.charisma)

    def to_sheet_dict(self) -> dict:
        return {
            "name": self.name,
            "race": self.race,
            "class": self.char_class,
            "level": self.level,
            "xp": self.xp,
            "hp": f"{self.current_hp}/{self.max_hp}",
            "ac": self.armor_class,
            "initiative": self.initiative_bonus,
            "speed": self.speed,
            "proficiency_bonus": self.proficiency_bonus,
            "stats": {
                "STR": f"{self.strength} ({self.str_mod:+d})",
                "DEX": f"{self.dexterity} ({self.dex_mod:+d})",
                "CON": f"{self.constitution} ({self.con_mod:+d})",
                "INT": f"{self.intelligence} ({self.int_mod:+d})",
                "WIS": f"{self.wisdom} ({self.wis_mod:+d})",
                "CHA": f"{self.charisma} ({self.cha_mod:+d})",
            },
            "proficient_skills": self.proficient_skills,
            "saving_throws": self.saving_throw_proficiencies,
            "gold": self.gold,
            "inventory": self.inventory,
            "conditions": self.conditions,
            "backstory": self.backstory,
        }
