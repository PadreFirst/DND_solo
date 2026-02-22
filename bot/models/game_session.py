from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    genre: Mapped[str] = mapped_column(String(50), default="fantasy")
    tone: Mapped[str] = mapped_column(String(50), default="epic")
    theme: Mapped[str] = mapped_column(String(100), default="classic")

    current_location: Mapped[str] = mapped_column(String(255), default="Unknown")
    current_quest: Mapped[str] = mapped_column(Text, default="")
    world_state: Mapped[str] = mapped_column(Text, default="{}")

    _message_history: Mapped[str] = mapped_column("message_history", Text, default="[]")
    summary: Mapped[str] = mapped_column(Text, default="")
    message_count: Mapped[int] = mapped_column(default=0)
    turn_number: Mapped[int] = mapped_column(default=0)

    _active_npcs: Mapped[str] = mapped_column("active_npcs", Text, default="[]")
    _active_enemies: Mapped[str] = mapped_column("active_enemies", Text, default="[]")
    in_combat: Mapped[bool] = mapped_column(default=False)

    _last_actions: Mapped[str] = mapped_column("last_actions", Text, default="[]")
    _last_action_styles: Mapped[str] = mapped_column("last_action_styles", Text, default="[]")
    currency_name: Mapped[str] = mapped_column(String(100), default="gold")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="game_session")

    @property
    def message_history(self) -> list[dict]:
        return json.loads(self._message_history)

    @message_history.setter
    def message_history(self, value: list[dict]) -> None:
        self._message_history = json.dumps(value, ensure_ascii=False)

    @property
    def active_npcs(self) -> list[dict]:
        return json.loads(self._active_npcs)

    @active_npcs.setter
    def active_npcs(self, value: list[dict]) -> None:
        self._active_npcs = json.dumps(value, ensure_ascii=False)

    @property
    def active_enemies(self) -> list[dict]:
        return json.loads(self._active_enemies)

    @active_enemies.setter
    def active_enemies(self, value: list[dict]) -> None:
        self._active_enemies = json.dumps(value, ensure_ascii=False)

    @property
    def last_actions(self) -> list[str]:
        try:
            return json.loads(self._last_actions)
        except Exception:
            return []

    @last_actions.setter
    def last_actions(self, value: list[str]) -> None:
        self._last_actions = json.dumps(value, ensure_ascii=False)

    @property
    def last_action_styles(self) -> list[str]:
        try:
            return json.loads(self._last_action_styles)
        except Exception:
            return []

    @last_action_styles.setter
    def last_action_styles(self, value: list[str]) -> None:
        self._last_action_styles = json.dumps(value, ensure_ascii=False)

    def append_message(self, role: str, content: str) -> None:
        history = self.message_history
        history.append({"role": role, "content": content})
        self.message_history = history
        self.message_count += 1

    def get_recent_messages(self, n: int = 20) -> list[dict]:
        return self.message_history[-n:]

    def to_state_dict(self) -> dict:
        return {
            "genre": self.genre,
            "tone": self.tone,
            "theme": self.theme,
            "location": self.current_location,
            "quest": self.current_quest,
            "world_state": self.world_state,
            "turn": self.turn_number,
            "in_combat": self.in_combat,
            "active_npcs": self.active_npcs,
            "active_enemies": self.active_enemies,
        }
