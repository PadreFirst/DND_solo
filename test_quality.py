"""Quality test: check narrative length, dice discipline, infodump, success/fail."""
import asyncio
import time
from dotenv import load_dotenv
load_dotenv()

from bot.services.gemini import GameResponse, generate_structured
from bot.services.prompt_builder import game_turn_prompt


async def test():
    context = """[SYSTEM INFO]
Character: Jean Dupont, Human Rogue Lv.1
HP: 10/10 | AC: 13
STR:10 DEX:15 CON:12 INT:14 WIS:11 CHA:13
Location: Dark underground tunnel, Soviet-era tiles on walls
Quest: Unknown - just escaped a digital creature through a wall glitch
Inventory: Dagger, Leather armor, Thieves tools, 15 gold, Cracked smartphone
There is a stranger named Shultz in the car. He just introduced himself.
Massive rusty blast doors with glowing purple symbols ahead.
History: Jean just arrived in secret Moscow. He knows NOTHING about this world. Shultz is the first person he met. Jean is confused and scared.
"""
    turns = [
        ("Спрашиваю Шульца: 'Кто ты такой и куда мы попали?'", "DIALOGUE - should have NO dice roll"),
        ("Выхожу из машины и осматриваю символы на воротах", "EXPLORATION - maybe 1 check max"),
        ("Пытаюсь вскрыть замок на воротах отмычками", "SKILL USE - should have a check"),
    ]

    for action, note in turns:
        prompt = game_turn_prompt(context, action, language="ru")
        start = time.monotonic()
        resp = await generate_structured(prompt, GameResponse, content_tier="adult")
        elapsed = time.monotonic() - start

        words = len(resp.narrative.split())
        checks = len(resp.skill_checks) + len(resp.saving_throws)

        print(f"\n{'='*60}")
        print(f"ACTION: {action}")
        print(f"NOTE: {note}")
        print(f"TIME: {elapsed:.1f}s | WORDS: {words} | CHECKS: {checks}")
        print(f"HAS_DIALOGUE: {resp.has_dialogue}")

        if words > 200:
            print(f"WARNING: Too long! {words} words (max 200)")
        if words < 30:
            print(f"WARNING: Too short! {words} words")

        print(f"\nNARRATIVE:\n{resp.narrative[:500]}")
        if resp.on_success:
            print(f"\nON_SUCCESS: {resp.on_success[:200]}")
        if resp.on_failure:
            print(f"\nON_FAILURE: {resp.on_failure[:200]}")
        print(f"\nACTIONS: {resp.available_actions}")


asyncio.run(test())
