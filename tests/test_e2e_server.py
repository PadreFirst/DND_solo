"""E2E test: run on server to verify Gemini API + char gen + mission gen work."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.gemini import generate_text, generate_structured, CharacterProposal, MissionProposal


async def test_gemini_text():
    print("[1/3] Testing generate_text...")
    try:
        r = await generate_text("Say hello in one word", temperature=0.1, max_tokens=20)
        print(f"  OK: {r.strip()}")
    except Exception as e:
        print(f"  FAIL: {e}")
        return False
    return True


async def test_char_gen():
    print("[2/3] Testing CharacterProposal generation...")
    try:
        from bot.services.prompt_builder import character_creation_prompt
        prompt = character_creation_prompt(
            user_description="Dark elf ranger, former assassin, seeks redemption",
            char_name="Drizzt",
            genre="Dark fantasy",
            tone="Dark, grim, morally gray.",
            theme="adventure",
            language="ru",
        )
        proposal = await generate_structured(prompt, CharacterProposal, heavy=True)
        print(f"  Name: {proposal.name}")
        print(f"  Race: {proposal.race}")
        print(f"  Class: {proposal.char_class}")
        print(f"  Skills: {proposal.proficient_skills}")
        print(f"  Backstory len: {len(proposal.backstory)} chars")
        if not proposal.backstory or len(proposal.backstory) < 20:
            print("  WARNING: Backstory too short!")
        if not proposal.proficient_skills:
            print("  WARNING: No proficient skills!")
        print("  OK")
    except Exception as e:
        print(f"  FAIL: {e}")
        return False
    return True


async def test_mission_gen():
    print("[3/3] Testing MissionProposal generation...")
    try:
        from bot.services.prompt_builder import mission_prompt
        prompt = mission_prompt(
            char_name="Drizzt",
            race="Dark Elf",
            char_class="Ranger",
            backstory="A former assassin of Menzoberranzan seeking redemption.",
            genre="Dark fantasy",
            tone="Dark, grim.",
            theme="adventure",
            language="ru",
        )
        mission = await generate_structured(prompt, MissionProposal, heavy=True)
        print(f"  Title: {mission.quest_title}")
        print(f"  Location: {mission.starting_location}")
        print(f"  Opening len: {len(mission.opening_scene)} chars")
        print(f"  NPC: {mission.first_npc_name} ({mission.first_npc_role})")
        if not mission.opening_scene or len(mission.opening_scene) < 50:
            print("  WARNING: Opening scene too short!")
        if not mission.quest_title:
            print("  WARNING: No quest title!")
        print("  OK")
    except Exception as e:
        print(f"  FAIL: {e}")
        return False
    return True


async def main():
    print("=== E2E Server Test ===\n")
    results = []
    results.append(await test_gemini_text())
    results.append(await test_char_gen())
    results.append(await test_mission_gen())

    print(f"\n=== Results: {sum(results)}/{len(results)} passed ===")
    if all(results):
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
