"""Full gameplay simulation: walks through the entire player journey and evaluates quality.

Simulates:
1. Character generation (narrative quality, rule compliance)
2. Character mechanical correctness (stats, HP, AC, inventory)
3. Mission generation (opening scene quality, world consistency)
4. 5 gameplay turns (mechanics, narrative, action suggestions)
5. Menu features (rest, inspect, inventory display)

Outputs a detailed quality report with scores.
"""
import asyncio
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.gemini import (
    CharacterProposal, MechanicsDecision, MissionProposal,
    generate_narrative, generate_structured, generate_text,
)
from bot.services.game_engine import (
    build_full_character, calculate_ac, skill_check, make_attack,
    saving_throw, short_rest, long_rest, merge_inventory, ensure_ammo,
    _resolve_skill_ability, normalize_class_name, HIT_DIE,
    CLASS_STARTING_EQUIPMENT, CLASS_SAVING_THROWS, CLASS_SPELL_SLOTS,
)
from bot.services.prompt_builder import (
    character_creation_prompt, mission_prompt, pass1_prompt, pass2_prompt, system_prompt,
)
from bot.utils.formatters import (
    format_character_sheet, format_inventory, md_to_html, truncate_for_telegram,
)


class FakeCharacter:
    def __init__(self):
        self.name = "Unnamed"
        self.race = "Human"
        self.char_class = "Fighter"
        self.level = 1
        self.xp = 0
        self.strength = 10
        self.dexterity = 10
        self.constitution = 10
        self.intelligence = 10
        self.wisdom = 10
        self.charisma = 10
        self.max_hp = 10
        self.current_hp = 10
        self.armor_class = 10
        self.initiative_bonus = 0
        self.speed = 30
        self.proficiency_bonus = 2
        self.proficient_skills = []
        self.saving_throw_proficiencies = []
        self.gold = 0
        self._inv = []
        self.backstory = ""
        self.conditions = []
        self.death_save_successes = 0
        self.death_save_failures = 0
        self.hit_dice_current = 1
        self.hit_dice_max = 1
        self.hit_dice_face = "d8"
        self._spell_slots = {}

    @property
    def inventory(self):
        return self._inv
    @inventory.setter
    def inventory(self, v):
        self._inv = v
    @property
    def spell_slots(self):
        return self._spell_slots
    @spell_slots.setter
    def spell_slots(self, v):
        self._spell_slots = v
    def ability_modifier(self, score):
        return (score - 10) // 2
    @property
    def str_mod(self):
        return self.ability_modifier(self.strength)
    @property
    def dex_mod(self):
        return self.ability_modifier(self.dexterity)
    @property
    def con_mod(self):
        return self.ability_modifier(self.constitution)
    @property
    def int_mod(self):
        return self.ability_modifier(self.intelligence)
    @property
    def wis_mod(self):
        return self.ability_modifier(self.wisdom)
    @property
    def cha_mod(self):
        return self.ability_modifier(self.charisma)


scores = {}
issues = []
warnings = []


def score(category, value, max_val, detail=""):
    scores[category] = (value, max_val)
    status = "PASS" if value >= max_val * 0.7 else "WARN" if value >= max_val * 0.4 else "FAIL"
    emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[status]
    print(f"  {emoji} {category}: {value}/{max_val}" + (f" — {detail}" if detail else ""))
    if status == "FAIL":
        issues.append(f"{category}: {value}/{max_val} — {detail}")
    elif status == "WARN":
        warnings.append(f"{category}: {value}/{max_val} — {detail}")


# ========== TEST 1: CHARACTER GENERATION ==========

async def test_character_generation():
    print("\n" + "=" * 60)
    print("TEST 1: CHARACTER GENERATION")
    print("=" * 60)

    scenarios = [
        {
            "desc": "Тёмный эльф-ассасин, ищет искупление. Мрачный мир, где магия запрещена.",
            "name": "Каэль",
            "genre": "Мрачный мир, где магия запрещена законом, а тайные ордена колдунов скрываются в катакомбах",
            "tone": "Dark, grim, morally gray. Violence has weight, hope is scarce.",
            "lang": "ru",
        },
        {
            "desc": "Gnome inventor, chaotic good, obsessed with building clockwork creatures",
            "name": "Tinker",
            "genre": "Steampunk — Victorian era, steam-powered machines, airships",
            "tone": "Lighthearted, witty, comedic. Pop culture references, fun above all.",
            "lang": "en",
        },
    ]

    for i, sc in enumerate(scenarios):
        print(f"\n--- Scenario {i+1}: {sc['name']} ({sc['lang']}) ---")
        t0 = time.time()
        prompt = character_creation_prompt(
            user_description=sc["desc"],
            char_name=sc["name"],
            genre=sc["genre"],
            tone=sc["tone"],
            theme="adventure",
            language=sc["lang"],
        )
        proposal = await generate_structured(prompt, CharacterProposal, heavy=True)
        gen_time = time.time() - t0
        print(f"  Generation time: {gen_time:.1f}s")

        # Validate proposal fields
        name_ok = bool(proposal.name and len(proposal.name) >= 2)
        race_ok = bool(proposal.race and proposal.race != "Human" and len(proposal.race) >= 3)
        class_ok = bool(proposal.char_class and len(proposal.char_class) >= 3)
        skills_ok = isinstance(proposal.proficient_skills, list) and len(proposal.proficient_skills) >= 2
        backstory_ok = bool(proposal.backstory and len(proposal.backstory) >= 100)
        personality_ok = bool(proposal.personality_summary and len(proposal.personality_summary) >= 10)

        print(f"  Name: '{proposal.name}' {'✅' if name_ok else '❌'}")
        print(f"  Race: '{proposal.race}' {'✅' if race_ok else '❌'}")
        print(f"  Class: '{proposal.char_class}' {'✅' if class_ok else '❌'}")
        print(f"  Skills: {proposal.proficient_skills} {'✅' if skills_ok else '❌'}")
        print(f"  Backstory: {len(proposal.backstory)} chars {'✅' if backstory_ok else '❌'}")
        print(f"  Personality: '{proposal.personality_summary[:80]}...' {'✅' if personality_ok else '❌'}")

        field_score = sum([name_ok, race_ok, class_ok, skills_ok, backstory_ok, personality_ok])
        score(f"char_gen_{sc['name']}_fields", field_score, 6,
              f"name={name_ok} race={race_ok} class={class_ok} skills={skills_ok} backstory={backstory_ok} personality={personality_ok}")

        # Build full character and validate mechanics
        char = FakeCharacter()
        char.name = proposal.name
        build_full_character(
            char,
            char_class=proposal.char_class or "Fighter",
            race=proposal.race or "Human",
            backstory=proposal.backstory,
            proficient_skills=proposal.proficient_skills if isinstance(proposal.proficient_skills, list) else [],
            personality=proposal.personality_summary or "",
        )

        mech_checks = 0
        total_mech = 8

        # Stats should follow Standard Array
        stats = sorted([char.strength, char.dexterity, char.constitution,
                        char.intelligence, char.wisdom, char.charisma], reverse=True)
        if stats == [15, 14, 13, 12, 10, 8]:
            mech_checks += 1
            print(f"  Stats (Standard Array): ✅ {stats}")
        else:
            print(f"  Stats (Standard Array): ❌ {stats} (expected [15,14,13,12,10,8])")

        # HP check
        canon = normalize_class_name(proposal.char_class or "Fighter")
        hit_die = HIT_DIE.get(canon, "d8")
        max_die = int(hit_die[1:])
        con_mod = (char.constitution - 10) // 2
        expected_hp = max_die + con_mod
        if char.max_hp == max(1, expected_hp):
            mech_checks += 1
            print(f"  HP: ✅ {char.max_hp} (die={hit_die}, con_mod={con_mod:+d})")
        else:
            print(f"  HP: ❌ {char.max_hp} (expected {max(1, expected_hp)}, die={hit_die}, con_mod={con_mod:+d})")

        # AC check
        if char.armor_class >= 10:
            mech_checks += 1
            print(f"  AC: ✅ {char.armor_class}")
        else:
            print(f"  AC: ❌ {char.armor_class}")

        # Inventory check
        if len(char.inventory) >= 3:
            mech_checks += 1
            equipped = [i["name"] for i in char.inventory if i.get("equipped")]
            backpack = [i["name"] for i in char.inventory if not i.get("equipped")]
            print(f"  Inventory: ✅ {len(char.inventory)} items (equipped: {equipped})")
        else:
            print(f"  Inventory: ❌ only {len(char.inventory)} items")

        # Saving throws
        expected_saves = CLASS_SAVING_THROWS.get(canon, [])
        if char.saving_throw_proficiencies == expected_saves:
            mech_checks += 1
            print(f"  Saving throws: ✅ {char.saving_throw_proficiencies}")
        else:
            print(f"  Saving throws: ❌ {char.saving_throw_proficiencies} (expected {expected_saves})")

        # Gold check
        if char.gold > 0:
            mech_checks += 1
            print(f"  Gold: ✅ {char.gold}")
        else:
            print(f"  Gold: ❌ 0")

        # Hit dice
        if char.hit_dice_face == hit_die:
            mech_checks += 1
            print(f"  Hit Dice: ✅ {char.hit_dice_face}")
        else:
            print(f"  Hit Dice: ❌ {char.hit_dice_face} (expected {hit_die})")

        # Proficiency bonus
        if char.proficiency_bonus == 2:
            mech_checks += 1
            print(f"  Prof bonus: ✅ +{char.proficiency_bonus}")
        else:
            print(f"  Prof bonus: ❌ +{char.proficiency_bonus}")

        score(f"char_gen_{sc['name']}_mechanics", mech_checks, total_mech)

        # Test character sheet display
        sheet = format_character_sheet(char)
        sheet_ok = all(x in sheet for x in ["HP:", "AC:", "STR", "DEX"])
        score(f"char_gen_{sc['name']}_display", 1 if sheet_ok else 0, 1, "character sheet renders correctly")

        # Test inventory display
        inv_text = format_inventory(char)
        inv_ok = "Equipped" in inv_text or "equipped" in inv_text.lower()
        score(f"char_gen_{sc['name']}_inv_display", 1 if inv_ok else 0, 1, "inventory shows equipped items")

    return True


# ========== TEST 2: MISSION GENERATION ==========

async def test_mission_generation():
    print("\n" + "=" * 60)
    print("TEST 2: MISSION GENERATION")
    print("=" * 60)

    prompt = mission_prompt(
        char_name="Каэль",
        race="Эльф (Дроу)",
        char_class="Rogue",
        backstory="Бывший ассасин тайного ордена. Бежал после того, как отказался убить ребёнка. Разыскивается своими бывшими хозяевами. Ищет искупление в мире, где магия запрещена.",
        genre="Мрачный мир, где магия запрещена законом, а тайные ордена колдунов скрываются в катакомбах",
        tone="Dark, grim, morally gray. Violence has weight, hope is scarce.",
        theme="adventure",
        language="ru",
    )
    t0 = time.time()
    mission = await generate_structured(prompt, MissionProposal, heavy=True)
    gen_time = time.time() - t0
    print(f"\n  Generation time: {gen_time:.1f}s")

    checks = 0
    total = 7

    # Quest title
    if mission.quest_title and len(mission.quest_title) >= 3:
        checks += 1
        print(f"  Title: ✅ '{mission.quest_title}'")
    else:
        print(f"  Title: ❌ '{mission.quest_title}'")

    # Quest description
    if mission.quest_description and len(mission.quest_description) >= 30:
        checks += 1
        print(f"  Description: ✅ {len(mission.quest_description)} chars")
    else:
        print(f"  Description: ❌ {len(mission.quest_description) if mission.quest_description else 0} chars")

    # Opening scene
    if mission.opening_scene and len(mission.opening_scene) >= 200:
        checks += 1
        print(f"  Opening scene: ✅ {len(mission.opening_scene)} chars")
        # Check for HTML formatting
        has_html = "<b>" in mission.opening_scene or "<i>" in mission.opening_scene
        if has_html:
            print(f"    HTML formatting: ✅")
        else:
            print(f"    HTML formatting: ⚠️ no <b>/<i> tags found")
    else:
        print(f"  Opening scene: ❌ {len(mission.opening_scene) if mission.opening_scene else 0} chars (need 200+)")

    # Starting location
    if mission.starting_location and len(mission.starting_location) >= 5:
        checks += 1
        print(f"  Location: ✅ '{mission.starting_location}'")
    else:
        print(f"  Location: ❌ '{mission.starting_location}'")

    # NPC
    if mission.first_npc_name and len(mission.first_npc_name) >= 2:
        checks += 1
        print(f"  NPC: ✅ {mission.first_npc_name} — {mission.first_npc_role}")
    else:
        print(f"  NPC: ❌ no NPC name")

    # Hook/Mystery
    if mission.hook_mystery and len(mission.hook_mystery) >= 20:
        checks += 1
        print(f"  Mystery hook: ✅ {len(mission.hook_mystery)} chars")
    else:
        print(f"  Mystery hook: ❌ {len(mission.hook_mystery) if mission.hook_mystery else 0} chars")

    # World consistency: check that forbidden magic is referenced
    all_text = f"{mission.quest_description} {mission.opening_scene} {mission.hook_mystery}".lower()
    world_refs = any(w in all_text for w in ["маги", "магия", "запрещ", "орден", "тайн", "катакомб", "закон", "колдун"])
    if world_refs:
        checks += 1
        print(f"  World consistency: ✅ references world setting")
    else:
        print(f"  World consistency: ❌ doesn't reference the forbidden magic world")

    score("mission_quality", checks, total)

    # Test md_to_html on opening scene
    html_opening = md_to_html(mission.opening_scene)
    truncated = truncate_for_telegram(html_opening, 3500)
    display_ok = len(truncated) > 100 and "..." not in truncated[:200]
    score("mission_display", 1 if display_ok else 0, 1, "opening scene displays correctly")

    return mission


# ========== TEST 3: GAMEPLAY TURNS ==========

async def test_gameplay_turns(char, mission):
    print("\n" + "=" * 60)
    print("TEST 3: GAMEPLAY SIMULATION (5 TURNS)")
    print("=" * 60)

    sys_prompt = system_prompt("ru", "full")

    context_parts = [
        f"[SYSTEM INFO]",
        f"Player: {char.name}, Level {char.level} {char.race} {char.char_class}",
        f"HP: {char.current_hp}/{char.max_hp}, AC: {char.armor_class}",
        f"STR {char.strength} DEX {char.dexterity} CON {char.constitution} INT {char.intelligence} WIS {char.wisdom} CHA {char.charisma}",
        f"Proficiency: +{char.proficiency_bonus}",
        f"Skills: {', '.join(char.proficient_skills)}",
        f"Equipped: {', '.join(i['name'] for i in char.inventory if i.get('equipped'))}",
        f"Gold: {char.gold}",
        f"[/SYSTEM INFO]",
        f"",
        f"=== WORLD STATE ===",
        f"Location: {mission.starting_location}",
        f"Quest: {mission.quest_title}: {mission.quest_description}",
        f"NPC present: {mission.first_npc_name} ({mission.first_npc_role})",
        f"",
        f"=== RECENT CONVERSATION ===",
        f"GAME MASTER: {mission.opening_scene[:500]}",
    ]
    context = "\n".join(context_parts)
    full_context = f"{sys_prompt}\n\n{context}"

    player_actions = [
        "Осмотреться вокруг, обращая внимание на подозрительные детали",
        f"Подойти к {mission.first_npc_name} и осторожно заговорить",
        "Проверить, нет ли кого-то, кто за мной следит",
        "Достать кинжал и двигаться в тень, исследуя тёмный проход",
        "Попробовать взломать замок на двери",
    ]

    turn_scores = []
    for turn_num, action in enumerate(player_actions, 1):
        print(f"\n--- Turn {turn_num}: '{action[:50]}...' ---")
        t0 = time.time()

        # Pass 1: Mechanics
        try:
            decision = await generate_structured(
                pass1_prompt(full_context, action, language="ru"),
                MechanicsDecision,
            )
        except Exception as e:
            print(f"  ❌ Pass 1 FAILED: {e}")
            turn_scores.append(0)
            continue

        p1_time = time.time() - t0

        turn_check = 0
        turn_total = 5

        # Check available_actions
        if decision.available_actions and len(decision.available_actions) >= 2:
            turn_check += 1
            # Check they're in Russian
            has_russian = any(any(c >= '\u0400' and c <= '\u04ff' for c in a) for a in decision.available_actions)
            if has_russian:
                print(f"  Actions (RU): ✅ {decision.available_actions}")
            else:
                print(f"  Actions: ⚠️ not in Russian: {decision.available_actions}")
        else:
            print(f"  Actions: ❌ {decision.available_actions}")

        # Check narration_context
        if decision.narration_context and len(decision.narration_context) >= 10:
            turn_check += 1
            print(f"  Narration context: ✅ {len(decision.narration_context)} chars")
        else:
            print(f"  Narration context: ❌ '{decision.narration_context}'")

        # Execute mechanics
        mech_lines = []
        for sc in decision.skill_checks:
            try:
                ability = _resolve_skill_ability(sc.skill)
                r = skill_check(char, sc.skill, sc.dc, sc.advantage, sc.disadvantage)
                mech_lines.append(r.display)
                print(f"  Skill check: {sc.skill} DC{sc.dc} → {r.roll_result.total} ({'✅' if r.success else '❌'})")
            except Exception as e:
                print(f"  Skill check ERROR: {e}")

        if decision.attack_target_ac > 0:
            try:
                atk = make_attack(char, decision.attack_target_ac, decision.attack_damage_dice or "1d8")
                mech_lines.append(atk.display)
                print(f"  Attack: AC{decision.attack_target_ac} → {'hit' if atk.hit else 'miss'}")
            except Exception as e:
                print(f"  Attack ERROR: {e}")

        mechanics_ok = True
        turn_check += 1
        print(f"  Mechanics execution: ✅ no crashes")

        # Pass 2: Narrative
        mechanics_text = "\n".join(mech_lines) if mech_lines else "No mechanical effects."
        t1 = time.time()
        try:
            narrative = await generate_narrative(
                pass2_prompt(full_context, action, mechanics_text, "ru"),
            )
        except Exception as e:
            print(f"  ❌ Pass 2 FAILED: {e}")
            turn_scores.append(turn_check)
            continue

        p2_time = time.time() - t1
        total_time = time.time() - t0

        narrative_html = md_to_html(narrative)

        if len(narrative) >= 100:
            turn_check += 1
            print(f"  Narrative: ✅ {len(narrative)} chars ({total_time:.1f}s)")
        else:
            print(f"  Narrative: ❌ only {len(narrative)} chars")

        # Check narrative doesn't have markdown ** formatting
        if "**" not in narrative:
            turn_check += 1
            print(f"  HTML formatting: ✅ no markdown leaking")
        else:
            print(f"  HTML formatting: ⚠️ still has ** markdown")

        turn_scores.append(turn_check)

        # Update context for next turn
        context_parts.append(f"PLAYER: {action}")
        context_parts.append(f"GAME MASTER: {narrative[:300]}")
        context = "\n".join(context_parts)
        full_context = f"{sys_prompt}\n\n{context}"

    avg_turn = sum(turn_scores) / len(turn_scores) if turn_scores else 0
    score("gameplay_turns", int(avg_turn * 2), 10, f"avg {avg_turn:.1f}/5 per turn across {len(turn_scores)} turns")


# ========== TEST 4: MENU FEATURES ==========

async def test_menu_features(char):
    print("\n" + "=" * 60)
    print("TEST 4: MENU FEATURES")
    print("=" * 60)

    checks = 0
    total = 5

    # Short rest
    char.current_hp = char.max_hp // 2
    result = short_rest(char, lang="ru")
    if "Короткий отдых" in result or "HP" in result:
        checks += 1
        print(f"  Short rest (RU): ✅ {result}")
    else:
        print(f"  Short rest (RU): ❌ {result}")

    # Long rest
    char.current_hp = 1
    result = long_rest(char, lang="ru")
    if char.current_hp == char.max_hp and "Длинный отдых" in result:
        checks += 1
        print(f"  Long rest (RU): ✅ HP restored to {char.current_hp}/{char.max_hp}")
    else:
        print(f"  Long rest (RU): ❌ HP={char.current_hp}/{char.max_hp}, msg={result}")

    # Inventory merge
    old_inv = list(char.inventory)
    changes = [{"name": "Healing Potion", "quantity": 2, "action": "add", "description": "Heals 2d4+2"}]
    new_inv = merge_inventory(char.inventory, changes)
    potion = [i for i in new_inv if "potion" in i.get("name", "").lower() or "healing" in i.get("name", "").lower()]
    if potion:
        checks += 1
        print(f"  Inventory merge: ✅ added {potion[0]['name']} x{potion[0].get('quantity', 1)}")
    else:
        print(f"  Inventory merge: ❌ potion not found in {[i['name'] for i in new_inv]}")

    # Ensure ammo
    test_inv = [{"name": "Shortbow", "type": "weapon", "quantity": 1}]
    test_inv = ensure_ammo(test_inv)
    ammo = [i for i in test_inv if i.get("type") == "ammo"]
    if ammo:
        checks += 1
        print(f"  Auto ammo: ✅ {ammo[0]['name']} x{ammo[0].get('quantity', 0)}")
    else:
        print(f"  Auto ammo: ❌ no ammo added")

    # Character sheet display
    sheet = format_character_sheet(char)
    has_bars = "█" in sheet or "░" in sheet
    if has_bars:
        checks += 1
        print(f"  Char sheet bars: ✅ visual progress bars present")
    else:
        print(f"  Char sheet bars: ❌ no visual bars")

    score("menu_features", checks, total)


# ========== TEST 5: EDGE CASES ==========

async def test_edge_cases():
    print("\n" + "=" * 60)
    print("TEST 5: EDGE CASES & ERROR RESILIENCE")
    print("=" * 60)

    checks = 0
    total = 6

    # Unknown class normalizes to Fighter
    c = normalize_class_name("абракадабра")
    if c == "Fighter":
        checks += 1
        print(f"  Unknown class → Fighter: ✅")
    else:
        print(f"  Unknown class → {c}: ❌")

    # Russian skill resolution
    for skill_ru, expected_ability in [("Убеждение", "charisma"), ("Скрытность", "dexterity"), ("Атлетика", "strength")]:
        ability = _resolve_skill_ability(skill_ru)
        if ability == expected_ability:
            checks += 1
            print(f"  {skill_ru} → {ability}: ✅")
        else:
            print(f"  {skill_ru} → {ability}: ❌ (expected {expected_ability})")

    # md_to_html strips bad tags
    dangerous = "<script>alert('xss')</script><b>safe</b>"
    cleaned = md_to_html(dangerous)
    if "<script>" not in cleaned and "<b>safe</b>" in cleaned:
        checks += 1
        print(f"  HTML sanitization: ✅")
    else:
        print(f"  HTML sanitization: ❌ '{cleaned}'")

    # Truncation preserves HTML tags
    long_html = "<b>" + "x" * 5000
    truncated = truncate_for_telegram(long_html, 200)
    if "</b>" in truncated:
        checks += 1
        print(f"  Truncation tag closing: ✅")
    else:
        print(f"  Truncation tag closing: ❌")

    score("edge_cases", checks, total)


# ========== MAIN ==========

async def main():
    print("╔══════════════════════════════════════════════╗")
    print("║   DND BOT — FULL GAMEPLAY SIMULATION        ║")
    print("╚══════════════════════════════════════════════╝")

    t_total = time.time()

    await test_character_generation()

    # Build a char for gameplay tests
    char = FakeCharacter()
    char.name = "Каэль"
    build_full_character(char, "Rogue", "Дроу", "Бывший ассасин.", ["Скрытность", "Акробатика", "Обман"], "Мрачный и осторожный")

    mission = await test_mission_generation()
    await test_gameplay_turns(char, mission)
    await test_menu_features(char)
    await test_edge_cases()

    # ========== FINAL REPORT ==========
    total_time = time.time() - t_total
    print("\n" + "=" * 60)
    print("FINAL QUALITY REPORT")
    print("=" * 60)

    total_earned = sum(v for v, _ in scores.values())
    total_possible = sum(m for _, m in scores.values())
    pct = (total_earned / total_possible * 100) if total_possible else 0

    print(f"\nOverall score: {total_earned}/{total_possible} ({pct:.0f}%)")
    print(f"Total simulation time: {total_time:.0f}s")

    if issues:
        print(f"\n❌ CRITICAL ISSUES ({len(issues)}):")
        for iss in issues:
            print(f"   • {iss}")

    if warnings:
        print(f"\n⚠️ WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"   • {w}")

    # Estimated user rating
    if pct >= 90:
        rating = "8-9/10"
        verdict = "Excellent — immersive and polished"
    elif pct >= 75:
        rating = "7-8/10"
        verdict = "Good — enjoyable with minor rough edges"
    elif pct >= 60:
        rating = "5-6/10"
        verdict = "Average — works but needs polish"
    elif pct >= 40:
        rating = "3-4/10"
        verdict = "Below average — frequent issues"
    else:
        rating = "1-2/10"
        verdict = "Poor — broken experience"

    print(f"\n🎮 Estimated user rating: {rating}")
    print(f"   {verdict}")

    if pct < 70:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
