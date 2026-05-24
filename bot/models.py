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
    # Universe-agnostic abilities (spells, Force powers, gadgets, racial
    # tricks — all go here). Each entry is an Ability (see schemas.py).
    # Note: Character.abilities_json above holds STR/DEX/etc scores; this
    # column is intentionally named `powers_json` to avoid the collision.
    powers_json: Mapped[str] = mapped_column(Text, default="[]")
    # Number of un-picked level-ups. Set on XP crossing, decremented when
    # the player picks a perk.
    pending_level_ups: Mapped[int] = mapped_column(Integer, default=0)
    # Cached LevelUpOffer (list of perks) awaiting the player's pick — lives
    # between /levelup and the `lvl:<id>` callback.
    pending_levelup_offer_json: Mapped[str] = mapped_column(Text, default="")
    known_recipes_json: Mapped[str] = mapped_column(Text, default="[]")
    attunement_json: Mapped[str] = mapped_column(Text, default='{"max":3,"items":[]}')
    rest_status_json: Mapped[str] = mapped_column(Text, default='{"short_rest_used":false,"long_rest_available":true}')

    # Death saves tracker — code rolls 1d20 at the start of every turn while
    # HP=0 and not stabilized/dead. Stored here so it survives between turns.
    death_saves_success: Mapped[int] = mapped_column(Integer, default=0)
    death_saves_failure: Mapped[int] = mapped_column(Integer, default=0)
    # Consecutive turns spent unconscious — counted across the death-save
    # loop. On N+ turns the engine ends combat (the enemies don't sit
    # around watching a corpse bleed out forever).
    consecutive_death_turns: Mapped[int] = mapped_column(Integer, default=0)

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

    # Guided onboarding wizard answers (universe + style) between the
    # button flow and the player's concept message. Cleared on consumption.
    onboarding_state_json: Mapped[str] = mapped_column(Text, default="")

    # Atomic scene goal — what the player must do RIGHT NOW. Rendered
    # above options every turn so they don't lose the thread.
    current_beat: Mapped[str] = mapped_column(String(160), default="")

    # Turn number on which the last `quest_events.create` fired. Used to
    # enforce a cooldown so the LLM can't spam the journal.
    last_quest_create_turn: Mapped[int] = mapped_column(Integer, default=0)

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
    # Turn-budget for time-pressure quests. 0 = no deadline. Code decrements
    # every turn and flips status to "failed" when it hits 0.
    deadline_turns_remaining: Mapped[int] = mapped_column(Integer, default=0)
    # Last turn this quest was created/updated. Drives auto-archival of
    # quests that haven't moved in a long time (journal hygiene).
    last_updated_turn: Mapped[int] = mapped_column(Integer, default=0)


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
    # True for bot-controlled allies who roll initiative with the player.
    is_companion: Mapped[bool] = mapped_column(Boolean, default=False)
    attack_bonus: Mapped[int] = mapped_column(Integer, default=3)
    damage_dice: Mapped[str] = mapped_column(String(24), default="1d6")
    damage_type: Mapped[str] = mapped_column(String(24), default="")
    initiative_bonus: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(120), default="")
    # Last turn this NPC was seen/mentioned. Drives "Recent NPCs:" replay
    # into the context so the LLM can callback recently-named characters.
    last_seen_turn: Mapped[int] = mapped_column(Integer, default=0)
    # Free-form short faction string. Used both for trade lookups and as
    # a callback hook ("the Yakuza haven't forgotten you stole their chip").
    faction: Mapped[str] = mapped_column(String(120), default="")
    # ── Relationship & memory fields (replay into every system prompt) ──
    # Bond strength −10..+10 (−10 mortal enemy, +10 inseparable ally).
    # Replaces attitude as the quantitative measure.
    bond: Mapped[int] = mapped_column(Integer, default=0)
    # Single short sentence — how the NPC speaks (gravelly, formal,
    # lispy). Helps LLM render consistent voice across appearances.
    speech_style: Mapped[str] = mapped_column(String(160), default="")
    # First-encounter snapshot — appearance + mannerisms. Set once,
    # rarely overwritten, so the NPC reads as the same person every time.
    appearance: Mapped[str] = mapped_column(Text, default="")
    # Free-form structured: promises[], debts[], secrets_known[],
    # gifts_received[], scars_caused[]. Stored as JSON list of short
    # strings so the LLM can callback ("ты ему ещё должен 200 кредитов").
    promises_json: Mapped[str] = mapped_column(Text, default="[]")
    debts_json: Mapped[str] = mapped_column(Text, default="[]")
    secrets_known_json: Mapped[str] = mapped_column(Text, default="[]")
    gifts_received_json: Mapped[str] = mapped_column(Text, default="[]")
    # Last memorable quote — gives the LLM a callback anchor and lets the
    # player recognise the NPC by voice on return.
    last_quote: Mapped[str] = mapped_column(Text, default="")
    # If the NPC died — turn number + cause. Ghost callbacks reference these
    # ("ты вспоминаешь, как Зек хрипел…" — turn N, cause).
    death_turn: Mapped[int] = mapped_column(Integer, default=0)
    death_cause: Mapped[str] = mapped_column(String(255), default="")


class FactionReputation(Base):
    __tablename__ = "faction_reputation"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    faction_name: Mapped[str] = mapped_column(String(255))
    reputation_score: Mapped[int] = mapped_column(Integer, default=0)
