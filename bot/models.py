from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255), default="")
    language: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    character: Mapped["Character"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    session: Mapped["GameSession"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    name: Mapped[str] = mapped_column(String(120), default="Безымянный")
    race: Mapped[str] = mapped_column(String(80), default="Human")
    char_class: Mapped[str] = mapped_column(String(80), default="Fighter")
    level: Mapped[int] = mapped_column(Integer, default=1)
    xp_current: Mapped[int] = mapped_column(Integer, default=0)
    xp_to_next_level: Mapped[int] = mapped_column(Integer, default=300)

    hp_current: Mapped[int] = mapped_column(Integer, default=12)
    hp_max: Mapped[int] = mapped_column(Integer, default=12)
    temp_hp: Mapped[int] = mapped_column(Integer, default=0)
    ac: Mapped[int] = mapped_column(Integer, default=12)
    speed_m: Mapped[int] = mapped_column(Integer, default=9)
    proficiency_bonus: Mapped[int] = mapped_column(Integer, default=2)
    gold: Mapped[int] = mapped_column(Integer, default=25)

    abilities_json: Mapped[str] = mapped_column(Text, default='{"STR":12,"DEX":12,"CON":12,"INT":10,"WIS":10,"CHA":10}')
    skill_proficiencies_json: Mapped[str] = mapped_column(Text, default="[]")
    saving_throw_proficiencies_json: Mapped[str] = mapped_column(Text, default="[]")
    conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    inventory_json: Mapped[str] = mapped_column(Text, default="[]")
    equipment_json: Mapped[str] = mapped_column(Text, default="{}")
    class_features_json: Mapped[str] = mapped_column(Text, default="[]")
    spell_slots_json: Mapped[str] = mapped_column(Text, default="{}")
    known_spells_json: Mapped[str] = mapped_column(Text, default="[]")
    known_recipes_json: Mapped[str] = mapped_column(Text, default="[]")
    attunement_json: Mapped[str] = mapped_column(Text, default='{"max":3,"items":[]}')
    rest_status_json: Mapped[str] = mapped_column(Text, default='{"short_rest_used":false,"long_rest_available":true}')

    # Death saves tracker — code rolls 1d20 at the start of every turn while
    # HP=0 and not stabilized/dead. Stored here so it survives between turns.
    death_saves_success: Mapped[int] = mapped_column(Integer, default=0)
    death_saves_failure: Mapped[int] = mapped_column(Integer, default=0)

    # {"resist":["fire"],"immune":["poison"],"vulnerable":["cold"]}
    resistances_json: Mapped[str] = mapped_column(Text, default='{"resist":[],"immune":[],"vulnerable":[]}')

    # Hit dice available for short rest (d8 per level for most classes).
    # Stored as a plain integer — the die type is implied by class.
    hit_dice_remaining: Mapped[int] = mapped_column(Integer, default=1)
    hit_dice_max: Mapped[int] = mapped_column(Integer, default=1)

    user: Mapped[User] = relationship(back_populates="character")

    def ability_mod(self, ability_key: str) -> int:
        abilities = json.loads(self.abilities_json or "{}")
        score = int(abilities.get(ability_key, 10))
        return (score - 10) // 2


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    universe: Mapped[str] = mapped_column(String(255), default="custom")
    narrative_style: Mapped[str] = mapped_column(String(80), default="эпический")
    current_location: Mapped[str] = mapped_column(String(255), default="Неизвестная локация")
    current_location_description: Mapped[str] = mapped_column(Text, default="")
    weather: Mapped[str] = mapped_column(String(40), default="clear")
    time_of_day: Mapped[str] = mapped_column(String(20), default="day")
    active_quest_summary: Mapped[str] = mapped_column(Text, default="")
    adventure_summary: Mapped[str] = mapped_column(Text, default="")

    combat_active: Mapped[bool] = mapped_column(Boolean, default=False)
    round_number: Mapped[int] = mapped_column(Integer, default=0)
    initiative_order_json: Mapped[str] = mapped_column(Text, default="[]")
    current_turn_index: Mapped[int] = mapped_column(Integer, default=0)
    action_used: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus_used: Mapped[bool] = mapped_column(Boolean, default=False)
    reaction_used: Mapped[bool] = mapped_column(Boolean, default=False)
    movement_remaining: Mapped[int] = mapped_column(Integer, default=9)

    last_options_json: Mapped[str] = mapped_column(Text, default="[]")
    turn_number: Mapped[int] = mapped_column(Integer, default=0)
    # Snapshot of enemies currently on the scene (see SceneEnemy schema).
    # Kept as JSON so we can extend it later without another migration.
    scene_state_json: Mapped[str] = mapped_column(Text, default="[]")

    # Whether the current scene has an active light source (torch, implant,
    # streetlight). Used by engine.compute_auto_modifiers to decide if "night"
    # applies a disadvantage on Perception and ranged attacks.
    has_light_source: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="session")


class MessageLog(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    giver: Mapped[str] = mapped_column(String(255), default="")
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="active")  # active/completed
    steps_json: Mapped[str] = mapped_column(Text, default="[]")
    progress_json: Mapped[str] = mapped_column(Text, default="{}")
    reward_xp: Mapped[int] = mapped_column(Integer, default=0)
    reward_gold: Mapped[int] = mapped_column(Integer, default=0)


class NPCState(Base):
    __tablename__ = "npc_state"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    current_location: Mapped[str] = mapped_column(String(255), default="")
    hp_current: Mapped[int] = mapped_column(Integer, default=10)
    hp_max: Mapped[int] = mapped_column(Integer, default=10)
    ac: Mapped[int] = mapped_column(Integer, default=10)
    attitude: Mapped[str] = mapped_column(String(40), default="neutral")
    inventory_json: Mapped[str] = mapped_column(Text, default="[]")
    statblock_json: Mapped[str] = mapped_column(Text, default="{}")
    is_quest_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class FactionReputation(Base):
    __tablename__ = "faction_reputation"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    faction_name: Mapped[str] = mapped_column(String(255))
    reputation_score: Mapped[int] = mapped_column(Integer, default=0)
