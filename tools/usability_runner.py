"""Usability test runner.

Walks through ~12 representative gameplay scenarios using the real Gemini
proxy on prod. For each scenario, prints:
  - what we did (action)
  - what the engine did under the hood (rolls, DB mutations)
  - what the player would actually see (chat text + options)
  - any side-effects (HP/XP/inventory/quest deltas)

Run with: python tools/usability_runner.py > usability_report.txt

The output is read by a human auditor — keep it scannable.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from sqlalchemy import select  # noqa: E402

from bot.db import SessionLocal, init_db  # noqa: E402
from bot.models import Character, GameSession, NPCState, Quest, User  # noqa: E402
from bot.services.game_service import GameService  # noqa: E402
from bot.services.gemini import GeminiClient  # noqa: E402

TG_ID = 90909


def hr(title: str = "") -> None:
    print("\n" + "=" * 78)
    if title:
        print(f"=== {title}")
        print("=" * 78)


def snap(label: str, ch: Character, gs: GameSession) -> str:
    inv = json.loads(ch.inventory_json or "[]")
    inv_brief = ", ".join(
        f"{i.get('emoji','•')} {i.get('name')}×{i.get('quantity', 1)}" for i in inv
    )
    return (
        f"[{label}] {ch.name} ({ch.race} {ch.char_class} lvl {ch.level}) | "
        f"HP {ch.hp_current}/{ch.hp_max} | XP {ch.xp_current}/{ch.xp_to_next_level} | "
        f"Gold {ch.gold} | Loc: {gs.current_location} | "
        f"Combat: {gs.combat_active} | Inv: {inv_brief or '(пусто)'}"
    )


async def dump_npcs(db, user_id: int) -> str:
    rows = list(await db.scalars(select(NPCState).where(NPCState.user_id == user_id)))
    if not rows:
        return "NPCs: (нет)"
    out = ["NPCs:"]
    for n in rows:
        flags = []
        if n.bond:
            flags.append(f"bond {n.bond:+d}")
        if n.death_turn:
            flags.append(f"† turn {n.death_turn}")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        out.append(
            f"  • {n.name} ({n.role or '?'}, {n.faction or 'без фракции'}, "
            f"{n.attitude}){flag_str}, last_seen turn {n.last_seen_turn}"
        )
        for lbl, raw in (("promises", n.promises_json), ("debts", n.debts_json),
                        ("secrets", n.secrets_known_json), ("gifts", n.gifts_received_json)):
            items = json.loads(raw or "[]")
            if items:
                out.append(f"      {lbl}: {items}")
    return "\n".join(out)


async def dump_quests(db, user_id: int) -> str:
    rows = list(await db.scalars(select(Quest).where(Quest.user_id == user_id)))
    if not rows:
        return "Quests: (нет)"
    out = ["Quests:"]
    for q in rows:
        d = f" ⏳{q.deadline_turns_remaining}" if q.deadline_turns_remaining else ""
        out.append(f"  • [{q.status}] {q.title}{d} (last_updated turn {q.last_updated_turn})")
    return "\n".join(out)


@asynccontextmanager
async def session():
    async with SessionLocal() as db:
        yield db
        await db.commit()


async def take(svc: GameService, action: str, label: str) -> None:
    """Run one player action, render what the user would see + side-effects."""
    async with session() as db:
        u = await svc.get_or_create_user(db, TG_ID, "audit")
        ch_before = await svc.ensure_character(db, u)
        gs_before = await svc.ensure_session(db, u)
        before = snap("BEFORE", ch_before, gs_before)
        print(f"\n--- ACTION: {label}")
        print(f"    > {action!r}")
        print(f"    {before}")
        try:
            out = await svc.process_turn(db, u, action)
        except Exception as exc:
            print(f"!!! EXCEPTION: {exc}")
            return
        ch_after = await svc.ensure_character(db, u)
        gs_after = await svc.ensure_session(db, u)
        print("    --- PLAYER SEES ---")
        for line in out.text.splitlines():
            print(f"    {line}")
        print(f"    --- OPTIONS ({len(out.options)}) ---")
        for i, o in enumerate(out.options, 1):
            print(f"      {i}) {o}")
        print(f"    --- AFTER ---")
        print(f"    {snap('AFTER ', ch_after, gs_after)}")
        print(f"    {await dump_npcs(db, u.id)}")
        print(f"    {await dump_quests(db, u.id)}")
        # Beat-line + current state
        if gs_after.current_beat:
            print(f"    Beat: 🎯 {gs_after.current_beat}")


async def main() -> None:
    await init_db()
    g = GeminiClient()
    svc = GameService(g)

    # ============ Scenario 0: fresh user, wizard prefs prefilled ============
    hr("SCENARIO 0 — Quick-start wizard prefs + initialize_story")
    print("Player simulation: tap 🚀 Быстрый старт on wizard, type concept.")
    async with session() as db:
        u = await svc.get_or_create_user(db, TG_ID, "audit")
        gs = await svc.ensure_session(db, u)
        gs.onboarding_state_json = json.dumps({
            "universe": "🌆 Киберпанк", "tone": "🌑 Тёмная и жёсткая",
            "rating": "18", "pace": "⚖ Средний", "difficulty": "⚖ Норма",
            "stake": "💔 Близкий человек (сестра, похищена)",
        }, ensure_ascii=False)
    async with session() as db:
        u = await svc.get_or_create_user(db, TG_ID, "audit")
        out = await svc.initialize_story(
            db, u, "Нетраннер-соло Рен, бывшая корп-безопасница, ищет похищенную сестру"
        )
        print("    --- PLAYER SEES (initialize_story) ---")
        for line in out.text.splitlines():
            print(f"    {line}")
        print(f"    --- OPTIONS ({len(out.options)}) ---")
        for i, o in enumerate(out.options, 1):
            print(f"      {i}) {o}")
        ch = await svc.ensure_character(db, u)
        gs = await svc.ensure_session(db, u)
        print(f"    {snap('AFTER', ch, gs)}")
        print(f"    Beat: 🎯 {gs.current_beat or '(пусто)'}")

    # ============ Scenarios 1-12: variety of player actions ============

    actions: list[tuple[str, str]] = [
        ("S1 — обычное действие (исследование)",
         "Осмотреть комнату внимательно, проверить замки на двери"),
        ("S2 — социалка (диалог)",
         "Спросить у бармена что слышно про корпорацию, которая забрала сестру"),
        ("S3 — скилл-чек с риском",
         "Тихо вскрыть дверь чёрного хода без шума"),
        ("S4 — атака в бой",
         "Выхватить пистолет и выстрелить в первого охранника в лицо"),
        ("S5 — попытка переговоров",
         "Угрожать охраннику что выложу видео в сеть если не пропустит"),
        ("S6 — ГМ-вопрос (мета)",
         "ГМ: что даёт мне Ловкость в киберпанке?"),
        ("S7 — лут / обыск",
         "Обыскать труп охранника, забрать оружие и чипы"),
        ("S8 — попытка крафта/импровизации",
         "Из найденных проводов и стимулятора собрать самодельный шокер"),
        ("S9 — побег от стычки",
         "Бросить дымовую гранату и сбежать в боковой переулок"),
        ("S10 — отдых",
         "Найти укромный угол и попытаться отдохнуть пару часов"),
        ("S11 — продолжение охоты",
         "Подключиться к местной сети и поискать след корпорации по чипу"),
        ("S12 — провокация (рискнуть всем)",
         "Войти в офис корпорации через парадный вход и потребовать встречи с боссом"),
    ]
    for label, action in actions:
        hr(label)
        await take(svc, action, label)

    # ============ Special: force conditions for scripted scenarios ============

    hr("SPECIAL — force HP=0 → death-save loop short-circuit")
    async with session() as db:
        u = await svc.get_or_create_user(db, TG_ID, "audit")
        ch = await svc.ensure_character(db, u)
        ch.hp_current = 0
        ch.death_saves_success = 0
        ch.death_saves_failure = 0
        # Clear stabilized/dead conditions if any.
        ch.conditions_json = "[]"
    await take(svc, "продолжить", "DEATH SAVE turn — HP=0 fallback")
    await take(svc, "продолжить", "DEATH SAVE turn 2")

    hr("SPECIAL — force XP over threshold → level-up trigger")
    async with session() as db:
        u = await svc.get_or_create_user(db, TG_ID, "audit")
        ch = await svc.ensure_character(db, u)
        ch.hp_current = ch.hp_max  # revive for test
        ch.conditions_json = "[]"
        ch.xp_current = ch.xp_to_next_level + 50
    await take(svc, "осмотреться", "LEVEL-UP turn (XP forced)")

    hr("FINAL STATE — full NPC + quest dump")
    async with session() as db:
        u = await svc.get_or_create_user(db, TG_ID, "audit")
        ch = await svc.ensure_character(db, u)
        gs = await svc.ensure_session(db, u)
        print(snap("FINAL", ch, gs))
        print(await dump_npcs(db, u.id))
        print(await dump_quests(db, u.id))
        print(f"\nAdventure summary ({len(gs.adventure_summary)} chars): {gs.adventure_summary[:500]!r}")

    await g.close()


if __name__ == "__main__":
    asyncio.run(main())
