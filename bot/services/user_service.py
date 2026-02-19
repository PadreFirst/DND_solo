"""DB helpers for loading / creating user, character, and session."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.character import Character
from bot.models.game_session import GameSession
from bot.models.user import OnboardingState, User


async def get_or_create_user(telegram_id: int, username: str | None, db: AsyncSession) -> User:
    result = await db.execute(
        select(User)
        .where(User.telegram_id == telegram_id)
        .options(
            selectinload(User.character),
            selectinload(User.game_session),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id, username=username)
        db.add(user)
        await db.flush()
    return user


async def ensure_character(user: User, db: AsyncSession) -> Character:
    if user.character is None:
        char = Character(user_id=user.id)
        db.add(char)
        await db.flush()
        user.character = char
    return user.character


async def ensure_session(user: User, db: AsyncSession) -> GameSession:
    if user.game_session is None:
        gs = GameSession(user_id=user.id)
        db.add(gs)
        await db.flush()
        user.game_session = gs
    return user.game_session


async def reset_game(user: User, db: AsyncSession) -> None:
    """Delete character and session to start over."""
    if user.character:
        await db.delete(user.character)
    if user.game_session:
        await db.delete(user.game_session)
    user.onboarding_state = OnboardingState.NEW
    await db.flush()
