"""Quick test: single-pass game turn latency and quality."""
import asyncio
import time
import os
from dotenv import load_dotenv
load_dotenv()

from bot.services.gemini import GameResponse, generate_structured
from bot.services.prompt_builder import game_turn_prompt


async def test():
    context = """[SYSTEM INFO]
Character: Jean Dupont, Human Rogue Lv.1
HP: 10/10 | AC: 13
STR:10 DEX:15 CON:12 INT:14 WIS:11 CHA:13
Location: Dark alley in Moscow
Quest: Discover the hidden magical underground
Inventory: Dagger, Leather armor, Thieves tools, 15 gold
History: Jean just arrived in Moscow. He knows NOTHING about magic or the hidden world. This is his first moment in the city.
"""
    actions = [
        ("Осторожно иду по тёмному переулку, прислушиваясь к звукам", "ru"),
        ("Подхожу к старой двери и пытаюсь открыть", "ru"),
        ("Разговариваю с бездомным, спрашиваю дорогу", "ru"),
    ]

    for action, lang in actions:
        prompt = game_turn_prompt(context, action, language=lang)
        start = time.monotonic()
        resp = await generate_structured(prompt, GameResponse, content_tier="adult")
        elapsed = time.monotonic() - start

        print(f"\n{'='*60}")
        print(f"ACTION: {action}")
        print(f"TIME: {elapsed:.1f}s")
        print(f"NARRATIVE ({len(resp.narrative)} chars): {resp.narrative[:200]}...")
        checks = len(resp.skill_checks)
        print(f"SKILL CHECKS: {checks}", end="")
        if checks:
            for sc in resp.skill_checks:
                print(f"  [{sc.skill} DC{sc.dc}]", end="")
        print()
        print(f"ACTIONS: {resp.available_actions}")

        if elapsed > 30:
            print("WARNING: >30s!")
        if checks > 0 and "прислушива" in action:
            print("NOTE: AI rolled dice for basic listening - prompt may need tuning")


asyncio.run(test())
