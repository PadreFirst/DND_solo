from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class ContentTier(str, enum.Enum):
    FULL = "full"
    MODERATE = "moderate"
    FAMILY = "family"


class AgeGroup(str, enum.Enum):
    TEEN = "13-15"
    YOUNG = "16-17"
    ADULT_YOUNG = "18-24"
    ADULT = "25-34"
    MATURE = "35+"


AGE_GROUP_DEFAULTS = {
    AgeGroup.TEEN: {
        "content_tier": ContentTier.FAMILY,
        "combat_pref": 0.6, "puzzle_pref": 0.5, "dialogue_pref": 0.3,
        "exploration_pref": 0.6, "romance_tolerance": 0.0, "gore_tolerance": 0.1,
        "humor_pref": 0.7, "engagement_level": 0.5,
    },
    AgeGroup.YOUNG: {
        "content_tier": ContentTier.MODERATE,
        "combat_pref": 0.6, "puzzle_pref": 0.4, "dialogue_pref": 0.4,
        "exploration_pref": 0.5, "romance_tolerance": 0.2, "gore_tolerance": 0.3,
        "humor_pref": 0.6, "engagement_level": 0.5,
    },
    AgeGroup.ADULT_YOUNG: {
        "content_tier": ContentTier.FULL,
        "combat_pref": 0.6, "puzzle_pref": 0.4, "dialogue_pref": 0.5,
        "exploration_pref": 0.5, "romance_tolerance": 0.5, "gore_tolerance": 0.5,
        "humor_pref": 0.5, "engagement_level": 0.5,
    },
    AgeGroup.ADULT: {
        "content_tier": ContentTier.FULL,
        "combat_pref": 0.5, "puzzle_pref": 0.5, "dialogue_pref": 0.6,
        "exploration_pref": 0.5, "romance_tolerance": 0.5, "gore_tolerance": 0.4,
        "humor_pref": 0.5, "engagement_level": 0.5,
    },
    AgeGroup.MATURE: {
        "content_tier": ContentTier.FULL,
        "combat_pref": 0.4, "puzzle_pref": 0.6, "dialogue_pref": 0.7,
        "exploration_pref": 0.5, "romance_tolerance": 0.5, "gore_tolerance": 0.4,
        "humor_pref": 0.5, "engagement_level": 0.5,
    },
}


class OnboardingState(str, enum.Enum):
    NEW = "new"
    LANG_ASKED = "lang_asked"
    AGE_ASKED = "age_asked"
    WORLD_SETUP = "world_setup"
    WORLD_CUSTOM = "world_custom"
    CHAR_NAME = "char_name"
    CHAR_METHOD = "char_method"
    CHAR_FREE_DESC = "char_free_desc"
    CHAR_Q1_RACE = "char_q1_race"
    CHAR_Q2_CLASS = "char_q2_class"
    CHAR_Q3_PERSONALITY = "char_q3_personality"
    CHAR_Q4_MOTIVATION = "char_q4_motivation"
    CHAR_Q5_QUIRK = "char_q5_quirk"
    CHAR_EXTRA = "char_extra"
    CHAR_GENERATING = "char_generating"
    CHAR_REVIEW = "char_review"
    MISSION_INTRO = "mission_intro"
    PLAYING = "playing"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    age_group: Mapped[str | None] = mapped_column(String(10), nullable=True)
    language: Mapped[str] = mapped_column(String(5), default="en")
    content_tier: Mapped[ContentTier] = mapped_column(
        Enum(ContentTier), default=ContentTier.FAMILY
    )
    onboarding_state: Mapped[OnboardingState] = mapped_column(
        Enum(OnboardingState), default=OnboardingState.NEW
    )

    combat_pref: Mapped[float] = mapped_column(Float, default=0.5)
    puzzle_pref: Mapped[float] = mapped_column(Float, default=0.5)
    dialogue_pref: Mapped[float] = mapped_column(Float, default=0.5)
    exploration_pref: Mapped[float] = mapped_column(Float, default=0.5)
    romance_tolerance: Mapped[float] = mapped_column(Float, default=0.3)
    gore_tolerance: Mapped[float] = mapped_column(Float, default=0.3)
    humor_pref: Mapped[float] = mapped_column(Float, default=0.5)
    engagement_level: Mapped[float] = mapped_column(Float, default=0.5)

    interaction_count: Mapped[int] = mapped_column(default=0)
    last_active: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    character: Mapped[Character | None] = relationship(
        "Character", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    game_session: Mapped[GameSession | None] = relationship(
        "GameSession", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    memories: Mapped[list[Memory]] = relationship(
        "Memory", back_populates="user", cascade="all, delete-orphan"
    )

    def apply_age_defaults(self, age_group: AgeGroup) -> None:
        self.age_group = age_group.value
        defaults = AGE_GROUP_DEFAULTS[age_group]
        self.content_tier = defaults["content_tier"]
        self.combat_pref = defaults["combat_pref"]
        self.puzzle_pref = defaults["puzzle_pref"]
        self.dialogue_pref = defaults["dialogue_pref"]
        self.exploration_pref = defaults["exploration_pref"]
        self.romance_tolerance = defaults["romance_tolerance"]
        self.gore_tolerance = defaults["gore_tolerance"]
        self.humor_pref = defaults["humor_pref"]
        self.engagement_level = defaults["engagement_level"]
