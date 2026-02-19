"""Adaptive personalization system.

Tracks player signals and periodically asks Gemini to re-evaluate
preference weights, which are then injected into the system prompt.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.models.game_session import GameSession
from bot.models.user import User
from bot.services.gemini import PersonalizationAnalysis, generate_structured
from bot.services.prompt_builder import personalization_prompt

log = logging.getLogger(__name__)


def track_interaction(user: User, message_text: str, response_time_ms: int | None = None) -> None:
    """Update simple engagement signals every interaction."""
    user.interaction_count += 1

    msg_len = len(message_text)
    if msg_len > 200:
        user.engagement_level = min(1.0, user.engagement_level + 0.02)
    elif msg_len < 10:
        user.engagement_level = max(0.0, user.engagement_level - 0.01)

    if response_time_ms is not None and response_time_ms < 5000:
        user.engagement_level = min(1.0, user.engagement_level + 0.01)


def track_action_choice(user: User, action: str) -> None:
    """Nudge weights based on what the player chooses."""
    action_lower = action.lower()

    combat_words = {"attack", "fight", "hit", "strike", "kill", "stab", "shoot", "slash",
                    "атак", "удар", "бить", "убить", "ударить", "стрел"}
    puzzle_words = {"examine", "investigate", "search", "inspect", "look", "puzzle", "riddle",
                    "осмотр", "исслед", "загадк", "поиск", "изучить"}
    dialogue_words = {"talk", "speak", "ask", "persuade", "negotiate", "convince",
                      "поговор", "спрос", "убедить", "сказать", "диалог"}
    explore_words = {"explore", "go", "move", "travel", "wander", "open",
                     "идти", "пойти", "двигать", "открыть", "исследовать"}

    delta = 0.03
    for word in combat_words:
        if word in action_lower:
            user.combat_pref = min(1.0, user.combat_pref + delta)
            return
    for word in puzzle_words:
        if word in action_lower:
            user.puzzle_pref = min(1.0, user.puzzle_pref + delta)
            return
    for word in dialogue_words:
        if word in action_lower:
            user.dialogue_pref = min(1.0, user.dialogue_pref + delta)
            return
    for word in explore_words:
        if word in action_lower:
            user.exploration_pref = min(1.0, user.exploration_pref + delta)
            return


async def maybe_run_deep_analysis(
    user: User,
    session: GameSession,
    db: AsyncSession,
) -> None:
    """Every N interactions, run full Gemini analysis of preferences."""
    if user.interaction_count % settings.personalization_every_n != 0:
        return
    if user.interaction_count < settings.personalization_every_n:
        return

    recent = session.get_recent_messages(30)
    if not recent:
        return

    interactions_text = "\n".join(
        f"{'PLAYER' if m['role'] == 'user' else 'GM'}: {m['content'][:200]}"
        for m in recent
    )
    current_weights = (
        f"combat: {user.combat_pref:.2f}, puzzle: {user.puzzle_pref:.2f}, "
        f"dialogue: {user.dialogue_pref:.2f}, exploration: {user.exploration_pref:.2f}, "
        f"romance: {user.romance_tolerance:.2f}, gore: {user.gore_tolerance:.2f}, "
        f"humor: {user.humor_pref:.2f}, engagement: {user.engagement_level:.2f}"
    )

    prompt = personalization_prompt(interactions_text, current_weights)

    try:
        analysis: PersonalizationAnalysis = await generate_structured(
            prompt, PersonalizationAnalysis, content_tier=user.content_tier.value
        )
        _apply_analysis(user, analysis)
        log.info(
            "Personalization updated for user %d: %s",
            user.telegram_id, analysis.reasoning[:100],
        )
    except Exception:
        log.exception("Personalization analysis failed for user %d", user.telegram_id)


def _apply_analysis(user: User, analysis: PersonalizationAnalysis) -> None:
    """Blend new analysis with existing weights (70% new, 30% old) for stability."""
    blend = 0.7
    user.combat_pref = blend * analysis.combat_pref + (1 - blend) * user.combat_pref
    user.puzzle_pref = blend * analysis.puzzle_pref + (1 - blend) * user.puzzle_pref
    user.dialogue_pref = blend * analysis.dialogue_pref + (1 - blend) * user.dialogue_pref
    user.exploration_pref = blend * analysis.exploration_pref + (1 - blend) * user.exploration_pref
    user.romance_tolerance = blend * analysis.romance_tolerance + (1 - blend) * user.romance_tolerance
    user.gore_tolerance = blend * analysis.gore_tolerance + (1 - blend) * user.gore_tolerance
    user.humor_pref = blend * analysis.humor_pref + (1 - blend) * user.humor_pref
    user.engagement_level = blend * analysis.engagement_level + (1 - blend) * user.engagement_level
