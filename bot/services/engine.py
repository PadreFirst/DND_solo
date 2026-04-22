from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field

from bot.models import Character, GameSession
from bot.services.dice import RollResult, roll_dice

SKILL_TO_ABILITY = {
    "атлетика": "STR",
    "акробатика": "DEX",
    "скрытность": "DEX",
    "ловкость рук": "DEX",
    "магия": "INT",
    "история": "INT",
    "анализ": "INT",
    "природа": "INT",
    "религия": "INT",
    "внимательность": "WIS",
    "проницательность": "WIS",
    "медицина": "WIS",
    "выживание": "WIS",
    "уход за животными": "WIS",
    "убеждение": "CHA",
    "обман": "CHA",
    "запугивание": "CHA",
    "выступление": "CHA",
}

ABILITY_RU = {
    "STR": "Сил", "DEX": "Лов", "CON": "Тел",
    "INT": "Инт", "WIS": "Мдр", "CHA": "Хар",
}

# Conditions that impose disadvantage on the character's OWN rolls. Mapped to
# the roll kind they affect. This is the "code enforces what the TZ promised".
# Source: system_prompt.md → Conditions table.
_COND_DISADV_ATTACK = {"poisoned", "blinded", "prone", "restrained", "frightened"}
_COND_DISADV_CHECK = {"poisoned", "frightened"}
_COND_DISADV_DEX_SAVE = {"restrained"}
_COND_INCAPACITATED = {"incapacitated", "stunned", "paralyzed", "unconscious", "petrified"}

# Weather/light impact. Kept intentionally shallow — full DM-grade tactical
# modifiers would need scene topology that we don't track yet.
_WEATHER_DISADV_RANGED = {"fog", "storm", "rain", "snow"}

_RANGED_HINTS = (
    "пистолет", "винтовк", "лук", "арбалет", "дротик", "мет", "снайпер",
    "револьвер", "дробовик", "стрел", "дальн", "ranged",
)
_PERCEPTION_HINTS = ("вниматель", "восприят", "perception", "слух")


def _norm_cond_set(raw: str | None) -> set[str]:
    """Turn character.conditions_json into a lowercase set of condition names."""
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return set()
    out: set[str] = set()
    for item in data:
        if isinstance(item, str):
            out.add(item.strip().lower())
        elif isinstance(item, dict):
            name = item.get("name") or item.get("id") or ""
            if name:
                out.add(str(name).strip().lower())
    return out


def compute_auto_modifiers(
    character: Character,
    gs: GameSession | None,
    *,
    roll_kind: str,          # "attack" | "check" | "save"
    label: str = "",
    ability_key: str = "",
) -> tuple[bool, bool, list[str]]:
    """Compute automatic advantage/disadvantage from conditions + environment.

    Returns (advantage, disadvantage, reasons). When both sides fire they
    cancel out per D&D 5e (→ both False). `reasons` is a human-readable list
    meant to be surfaced to the player as "почему помеха/преимущество".
    """
    adv_reasons: list[str] = []
    dis_reasons: list[str] = []

    label_low = (label or "").lower()
    is_ranged = any(h in label_low for h in _RANGED_HINTS)
    is_perception = any(h in label_low for h in _PERCEPTION_HINTS)

    conds = _norm_cond_set(getattr(character, "conditions_json", None))
    if roll_kind == "attack":
        for bad in _COND_DISADV_ATTACK & conds:
            dis_reasons.append(bad)
        # Invisible → advantage on own attacks
        if "invisible" in conds:
            adv_reasons.append("invisible")
    elif roll_kind == "check":
        for bad in _COND_DISADV_CHECK & conds:
            dis_reasons.append(bad)
    elif roll_kind == "save":
        if ability_key.upper() == "DEX" and (_COND_DISADV_DEX_SAVE & conds):
            dis_reasons.append("restrained")

    # Environment — only if we have a session to look at.
    if gs is not None:
        weather = (gs.weather or "").lower()
        tod = (gs.time_of_day or "").lower()
        no_light = not bool(getattr(gs, "has_light_source", True))

        if roll_kind == "attack" and is_ranged:
            if weather in _WEATHER_DISADV_RANGED:
                dis_reasons.append(f"погода:{weather}")
            if tod == "night" and no_light:
                dis_reasons.append("темнота")
        elif roll_kind == "check" and is_perception:
            if weather in {"fog", "storm", "snow"}:
                dis_reasons.append(f"погода:{weather}")
            if tod == "night" and no_light:
                dis_reasons.append("темнота")

    adv = bool(adv_reasons)
    dis = bool(dis_reasons)
    # Cancel out per 5e rule.
    if adv and dis:
        return False, False, adv_reasons + dis_reasons
    return adv, dis, adv_reasons + dis_reasons


@dataclass
class RichRoll:
    """Detailed roll breakdown for user-facing display."""
    label: str
    d20: int
    d20_alt: int | None  # second die for advantage/disadvantage
    advantage: bool
    disadvantage: bool
    ability_key: str
    ability_mod_value: int
    proficiency_value: int  # 0 if not proficient
    total: int
    dc: int
    success: bool
    # Reasons for advantage/disadvantage/cancellation, e.g. ["poisoned","темнота"]
    reasons: list[str] = field(default_factory=list)

    def format(self, *, kind: str = "Проверка") -> str:
        parts: list[str] = []

        if self.d20_alt is not None:
            tag = "преим." if self.advantage else "помеха"
            chosen = max(self.d20, self.d20_alt) if self.advantage else min(self.d20, self.d20_alt)
            parts.append(f"d20[{self.d20},{self.d20_alt}]→{chosen} ({tag})")
        else:
            parts.append(f"d20={self.d20}")

        ab_short = ABILITY_RU.get(self.ability_key, self.ability_key)
        if self.ability_mod_value != 0:
            parts.append(f"{ab_short} {self.ability_mod_value:+d}")
        else:
            parts.append(f"{ab_short} +0")

        if self.proficiency_value:
            parts.append(f"мастерство {self.proficiency_value:+d}")

        dc_label = "КД" if kind == "Атака" else "DC"
        result = "Успех" if self.success else "Провал"
        if kind == "Атака":
            result = "Попадание" if self.success else "Промах"

        out = f"🎲 {kind} {self.label}: {', '.join(parts)} → {self.total} vs {dc_label} {self.dc} — {result}"
        if self.reasons:
            out += f"  [{', '.join(self.reasons)}]"
        return out


def ability_mod(character: Character, key: str) -> int:
    abilities = json.loads(character.abilities_json or "{}")
    score = int(abilities.get(key.upper(), 10))
    return (score - 10) // 2


def make_skill_check(
    character: Character,
    skill_name: str,
    dc: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
    gs: GameSession | None = None,
    reputation_score: int | None = None,
) -> RichRoll:
    key = SKILL_TO_ABILITY.get(skill_name.strip().lower(), "WIS")
    mod = ability_mod(character, key)
    profs = [s.lower() for s in json.loads(character.skill_proficiencies_json or "[]")]
    prof_bonus = character.proficiency_bonus if skill_name.strip().lower() in profs else 0
    total_mod = mod + prof_bonus

    auto_adv, auto_dis, reasons = compute_auto_modifiers(
        character, gs, roll_kind="check", label=skill_name, ability_key=key,
    )
    # Encumbered → disadvantage on STR/DEX/CON checks (simplified 5e rule).
    if is_encumbered(character) and key in ("STR", "DEX", "CON"):
        auto_dis = True
        reasons.append("перегруз")
    adv = advantage or auto_adv
    dis = disadvantage or auto_dis
    if adv and dis:
        adv = dis = False

    # Faction reputation modifier on social skills. Only applied when the
    # caller supplies an NPC's faction rep score — keeps non-social rolls
    # untouched.
    rep_mod = 0
    if reputation_score is not None and is_social_skill(skill_name):
        rep_mod = reputation_modifier(reputation_score)
        total_mod += rep_mod
        if rep_mod:
            sign = "+" if rep_mod > 0 else ""
            reasons.append(f"репутация {sign}{rep_mod}")

    d20, d20_alt = _roll_d20(adv, dis)
    chosen = _pick_d20(d20, d20_alt, adv, dis)
    total = chosen + total_mod

    return RichRoll(
        label=skill_name.capitalize(),
        d20=d20, d20_alt=d20_alt,
        advantage=adv, disadvantage=dis,
        ability_key=key, ability_mod_value=mod,
        proficiency_value=prof_bonus + rep_mod,
        total=total, dc=dc, success=total >= dc,
        reasons=reasons,
    )


def make_attack_roll(
    character: Character,
    target_ac: int,
    *,
    ability_key: str = "STR",
    advantage: bool = False,
    disadvantage: bool = False,
    label: str = "атака",
    gs: GameSession | None = None,
) -> RichRoll:
    mod = ability_mod(character, ability_key)
    prof_bonus = character.proficiency_bonus

    auto_adv, auto_dis, reasons = compute_auto_modifiers(
        character, gs, roll_kind="attack", label=label, ability_key=ability_key,
    )
    adv = advantage or auto_adv
    dis = disadvantage or auto_dis
    if adv and dis:
        adv = dis = False

    d20, d20_alt = _roll_d20(adv, dis)
    chosen = _pick_d20(d20, d20_alt, adv, dis)
    total = chosen + mod + prof_bonus

    return RichRoll(
        label=label,
        d20=d20, d20_alt=d20_alt,
        advantage=adv, disadvantage=dis,
        ability_key=ability_key, ability_mod_value=mod,
        proficiency_value=prof_bonus,
        total=total, dc=target_ac, success=total >= target_ac,
        reasons=reasons,
    )


def make_save_roll(
    character: Character,
    ability_key: str,
    dc: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
    gs: GameSession | None = None,
) -> RichRoll:
    mod = ability_mod(character, ability_key)
    save_profs = [s.upper() for s in json.loads(character.saving_throw_proficiencies_json or "[]")]
    prof_bonus = character.proficiency_bonus if ability_key.upper() in save_profs else 0

    auto_adv, auto_dis, reasons = compute_auto_modifiers(
        character, gs, roll_kind="save", label="", ability_key=ability_key,
    )
    adv = advantage or auto_adv
    dis = disadvantage or auto_dis
    if adv and dis:
        adv = dis = False

    d20, d20_alt = _roll_d20(adv, dis)
    chosen = _pick_d20(d20, d20_alt, adv, dis)
    total = chosen + mod + prof_bonus

    ab_label = ABILITY_RU.get(ability_key.upper(), ability_key)
    return RichRoll(
        label=ab_label,
        d20=d20, d20_alt=d20_alt,
        advantage=adv, disadvantage=dis,
        ability_key=ability_key, ability_mod_value=mod,
        proficiency_value=prof_bonus,
        total=total, dc=dc, success=total >= dc,
        reasons=reasons,
    )


def roll_damage(dice_expr: str, ability_mod_value: int = 0, *, critical: bool = False) -> tuple[int, str]:
    """Roll a weapon damage expression like "1d8", "2d6+3", "1d10-1".

    Returns (total, human-readable detail). When critical=True the number of
    dice is doubled (but the flat modifier is NOT doubled — standard D&D 5e).
    ability_mod_value is added on top ONLY when the expression doesn't
    already carry its own modifier, so LLM-supplied strings with explicit
    "+MOD" still work correctly.
    """
    expr = (dice_expr or "").strip()
    if not expr:
        return 0, ""

    m = _DMG_RE.match(expr)
    if not m:
        # Unparseable — fall back to a flat roll via the dice service.
        try:
            r = roll_dice(expr)
            return max(0, r.total), f"{expr} → {r.total}"
        except Exception:
            return 0, expr

    count = int(m.group(1))
    sides = int(m.group(2))
    flat = int((m.group(3) or "0").replace(" ", ""))
    has_explicit_mod = bool(m.group(3))

    actual_count = count * 2 if critical else count
    rolls = [random.randint(1, sides) for _ in range(actual_count)]
    dice_total = sum(rolls)

    mod_part = flat if has_explicit_mod else ability_mod_value
    total = max(0, dice_total + mod_part)

    bits = [f"{actual_count}d{sides}{rolls}"]
    if mod_part:
        bits.append(f"{mod_part:+d}")
    if critical:
        bits.append("(крит ×2 кости)")
    return total, " ".join(bits) + f" → {total}"


_DMG_RE = re.compile(r"^\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


def apply_hp_change(character: Character, delta: int) -> tuple[int, int]:
    """Legacy: plain HP change without damage-type modifiers."""
    return apply_damage(character, delta, damage_type="")


def apply_damage(
    character: Character,
    delta: int,
    damage_type: str = "",
) -> tuple[int, int]:
    """Apply damage (delta<0) or healing (delta>0) honouring resistances.

    - Resistance → |dmg| // 2
    - Immunity   → |dmg| = 0
    - Vulnerability → |dmg| × 2
    Modifiers only apply to damage (delta < 0), not to healing.
    """
    old = character.hp_current
    if delta < 0 and damage_type:
        res = _resist_map(character)
        dmg = abs(delta)
        dtype = damage_type.strip().lower()
        if dtype in res.get("immune", []):
            dmg = 0
        elif dtype in res.get("resist", []):
            dmg = dmg // 2
        elif dtype in res.get("vulnerable", []):
            dmg = dmg * 2
        delta = -dmg

    if delta < 0:
        remaining_damage = abs(delta)
        if character.temp_hp > 0:
            absorbed = min(character.temp_hp, remaining_damage)
            character.temp_hp -= absorbed
            remaining_damage -= absorbed
        character.hp_current = max(0, character.hp_current - remaining_damage)
    elif delta > 0:
        character.hp_current = min(character.hp_max, character.hp_current + delta)
    return old, character.hp_current


def _resist_map(character: Character) -> dict[str, list[str]]:
    try:
        data = json.loads(character.resistances_json or "{}")
    except Exception:
        return {"resist": [], "immune": [], "vulnerable": []}
    return {
        "resist": [s.strip().lower() for s in data.get("resist", []) if isinstance(s, str)],
        "immune": [s.strip().lower() for s in data.get("immune", []) if isinstance(s, str)],
        "vulnerable": [s.strip().lower() for s in data.get("vulnerable", []) if isinstance(s, str)],
    }


# ─── Death saves ──────────────────────────────────────────────────────────

@dataclass
class DeathSaveResult:
    d20: int
    is_crit_success: bool   # nat20 → instantly wake with 1 HP
    is_crit_fail: bool      # nat1  → counts as 2 fails
    success: bool           # 10+
    successes: int
    failures: int
    stabilized: bool        # 3 successes OR nat20 woke up
    dead: bool              # 3 failures
    woke_up: bool           # nat20

    def format(self) -> str:
        icons = "✅" * self.successes + "❌" * self.failures
        head = f"💀 Спасбросок смерти: d20={self.d20}"
        if self.is_crit_success:
            head += " (nat20 → встаёшь с 1 HP)"
        elif self.is_crit_fail:
            head += " (nat1 → два провала)"
        elif self.success:
            head += " → успех"
        else:
            head += " → провал"
        tail = f"  [{icons or '—'}]"
        return head + tail


def roll_death_save(character: Character) -> DeathSaveResult:
    """Roll one death save, mutate character counters, return the result.

    Rules (from system_prompt.md):
      - 10+ → success
      - 1–9 → failure
      - nat20 → wake up with 1 HP (reset counters)
      - nat1 → 2 failures
      - 3 successes → stabilized
      - 3 failures → dead
    """
    d20 = random.randint(1, 20)
    is_nat20 = d20 == 20
    is_nat1 = d20 == 1

    if is_nat20:
        character.death_saves_success = 0
        character.death_saves_failure = 0
        character.hp_current = max(1, character.hp_current)
        if character.hp_current == 0:
            character.hp_current = 1
        return DeathSaveResult(
            d20=d20, is_crit_success=True, is_crit_fail=False,
            success=True, successes=0, failures=0,
            stabilized=True, dead=False, woke_up=True,
        )

    if is_nat1:
        character.death_saves_failure = min(3, character.death_saves_failure + 2)
    elif d20 >= 10:
        character.death_saves_success = min(3, character.death_saves_success + 1)
    else:
        character.death_saves_failure = min(3, character.death_saves_failure + 1)

    stabilized = character.death_saves_success >= 3
    dead = character.death_saves_failure >= 3
    if stabilized and not dead:
        character.death_saves_success = 0
        character.death_saves_failure = 0

    return DeathSaveResult(
        d20=d20, is_crit_success=False, is_crit_fail=is_nat1,
        success=d20 >= 10,
        successes=character.death_saves_success,
        failures=character.death_saves_failure,
        stabilized=stabilized, dead=dead, woke_up=False,
    )


# ─── Rest ─────────────────────────────────────────────────────────────────

def perform_short_rest(character: Character) -> list[str]:
    """Short rest: spend 1 Hit Die to recover HP, clear stabilized. Returns
    human-readable lines for the chat log.
    """
    lines: list[str] = []
    if character.hit_dice_remaining <= 0:
        lines.append("🕒 Короткий отдых: костей хитов нет — отдохнуть удалось, но HP не восстановлено.")
    else:
        character.hit_dice_remaining -= 1
        hd_roll = random.randint(1, 8)
        con_mod = ability_mod(character, "CON")
        heal = max(1, hd_roll + con_mod)
        old, new = apply_damage(character, heal, damage_type="")
        lines.append(f"🕒 Короткий отдых: d8={hd_roll} +Тел {con_mod:+d} → +{heal} HP ({old} → {new})")
        lines.append(f"   Костей хитов осталось: {character.hit_dice_remaining}/{character.hit_dice_max}")

    # Clear ephemeral conditions tied to combat exertion.
    conds = _norm_cond_set(character.conditions_json)
    for c in ("stabilized",):
        if c in conds:
            conds.discard(c)
    character.conditions_json = json.dumps(sorted(conds), ensure_ascii=False)
    return lines


def perform_long_rest(character: Character) -> list[str]:
    """Long rest: full HP, reset death saves, restore hit dice up to half,
    remove one level of Exhaustion. Returns chat-facing summary lines.
    """
    lines: list[str] = []
    old_hp = character.hp_current
    character.hp_current = character.hp_max
    character.temp_hp = 0
    character.death_saves_success = 0
    character.death_saves_failure = 0
    restored = max(1, character.hit_dice_max // 2)
    character.hit_dice_remaining = min(character.hit_dice_max, character.hit_dice_remaining + restored)
    character.rest_status_json = '{"short_rest_used":false,"long_rest_available":true}'

    # Clear typical "combat-scoped" conditions, step Exhaustion down by 1.
    conds = _norm_cond_set(character.conditions_json)
    cleared: list[str] = []
    for c in ("poisoned", "frightened", "unconscious", "stabilized", "prone", "grappled"):
        if c in conds:
            conds.discard(c)
            cleared.append(c)
    # Exhaustion: stored as "exhaustion" (level not tracked numerically here).
    # Step one level (= remove the flag if present).
    if "exhaustion" in conds:
        conds.discard("exhaustion")
        cleared.append("exhaustion −1")
    character.conditions_json = json.dumps(sorted(conds), ensure_ascii=False)

    lines.append(f"🌙 Длинный отдых завершён.")
    lines.append(f"♥ HP восстановлено: {old_hp} → {character.hp_current}")
    lines.append(f"🎲 Костей хитов: {character.hit_dice_remaining}/{character.hit_dice_max}")
    if cleared:
        lines.append(f"✨ Сняты состояния: {', '.join(cleared)}")
    return lines


# ─── Passive perception / carrying / attunement / reputation ────────────

def passive_perception(character: Character) -> int:
    """5e formula: PP = 10 + WIS mod + prof_bonus (if proficient in perception).

    We use the Russian label 'внимательность' as the perception skill name —
    matches SKILL_TO_ABILITY.
    """
    wis_mod = ability_mod(character, "WIS")
    profs = [s.lower() for s in json.loads(character.skill_proficiencies_json or "[]")]
    prof_bonus = character.proficiency_bonus if "внимательность" in profs else 0
    return 10 + wis_mod + prof_bonus


def carrying_capacity_kg(character: Character) -> float:
    """Simplified 5e: carrying capacity = STR × 7 kg (TZ rule). When the
    player exceeds this they become encumbered.
    """
    abilities = json.loads(character.abilities_json or "{}")
    str_score = int(abilities.get("STR", 10) or 10)
    return float(str_score * 7)


def current_carry_weight_kg(character: Character) -> float:
    """Sum of weight_kg × quantity across the inventory. Items without
    weight are treated as 0 — the LLM populates this field for anything
    meaningfully heavy.
    """
    try:
        inv = json.loads(character.inventory_json or "[]")
    except Exception:
        return 0.0
    total = 0.0
    for it in inv:
        w = float(it.get("weight_kg", 0) or 0)
        q = int(it.get("quantity", 1) or 1)
        total += w * q
    return total


def is_encumbered(character: Character) -> bool:
    return current_carry_weight_kg(character) > carrying_capacity_kg(character)


def reputation_modifier(score: int) -> int:
    """Faction reputation (-100..100) → modifier on social checks.

    Piecewise step (TZ: «репутация двигает соц-бросок»):
      |score| <  20   → 0
      |score| 20..49 → ±1
      |score| 50..79 → ±2
      |score| ≥ 80    → ±3
    """
    s = int(score or 0)
    mag = abs(s)
    if mag < 20:
        return 0
    if mag < 50:
        step = 1
    elif mag < 80:
        step = 2
    else:
        step = 3
    return step if s > 0 else -step


_SOCIAL_SKILLS = {"убеждение", "обман", "запугивание", "выступление", "проницательность"}


def is_social_skill(label: str) -> bool:
    return (label or "").strip().lower() in _SOCIAL_SKILLS


# ─── Attunement ──────────────────────────────────────────────────────────

def _attunement_data(character: Character) -> dict:
    try:
        data = json.loads(character.attunement_json or '{"max":3,"items":[]}')
    except Exception:
        data = {"max": 3, "items": []}
    data.setdefault("max", 3)
    data.setdefault("items", [])
    return data


def attuned_items(character: Character) -> list[str]:
    return [str(x) for x in _attunement_data(character).get("items", [])]


def attunement_max(character: Character) -> int:
    return int(_attunement_data(character).get("max", 3) or 3)


def add_attunement(character: Character, item_name: str) -> tuple[bool, str]:
    """Attune `item_name`. Returns (ok, reason). Enforces TZ limit (3)."""
    data = _attunement_data(character)
    name = (item_name or "").strip()
    if not name:
        return False, "Не указан предмет."
    low_items = [s.lower() for s in data["items"]]
    if name.lower() in low_items:
        return False, f"{name} уже настроен."
    if len(data["items"]) >= int(data.get("max", 3) or 3):
        return False, f"Достигнут лимит настройки ({data['max']}). Сначала сними что-нибудь."
    data["items"].append(name)
    character.attunement_json = json.dumps(data, ensure_ascii=False)
    return True, f"{name} настроен."


def remove_attunement(character: Character, item_name: str) -> tuple[bool, str]:
    data = _attunement_data(character)
    low = (item_name or "").strip().lower()
    for i, it in enumerate(list(data["items"])):
        if str(it).lower() == low:
            data["items"].pop(i)
            character.attunement_json = json.dumps(data, ensure_ascii=False)
            return True, f"{it} снят."
    return False, f"«{item_name}» не в списке настроенных."


# ─── Combat state machine ─────────────────────────────────────────────────
#
# Stored on GameSession in plain columns (initiative_order_json, round_number,
# current_turn_index, action_used, bonus_used, reaction_used,
# movement_remaining). This block keeps the math in one place and never
# reaches into the DB directly — the caller commits.

def start_combat(gs: GameSession, character: Character, scene: list[dict]) -> list[dict]:
    """Roll initiative for the player + every live enemy and store the
    order back onto GameSession. Returns the full initiative order list of
    {name, init, side, is_player} dicts.
    """
    dex_mod = ability_mod(character, "DEX")
    player_init = random.randint(1, 20) + dex_mod
    order: list[dict] = [
        {"name": character.name or "Герой", "init": player_init,
         "side": "player", "is_player": True},
    ]
    for enemy in scene:
        if int(enemy.get("hp_current", 0) or 0) <= 0:
            continue
        # Enemies without stats get a middling +0 init — stable & predictable.
        enemy_init = random.randint(1, 20) + int(enemy.get("dex_mod", 0) or 0)
        order.append({
            "name": enemy.get("name") or "Враг",
            "init": enemy_init,
            "side": "enemy",
            "is_player": False,
        })
    order.sort(key=lambda x: x["init"], reverse=True)

    gs.combat_active = True
    gs.initiative_order_json = json.dumps(order, ensure_ascii=False)
    gs.round_number = 1
    gs.current_turn_index = 0
    reset_action_economy(gs, character)
    return order


def end_combat(gs: GameSession) -> None:
    """Leave combat cleanly — wipe initiative, reset round counter."""
    gs.combat_active = False
    gs.initiative_order_json = "[]"
    gs.round_number = 0
    gs.current_turn_index = 0
    gs.action_used = False
    gs.bonus_used = False
    gs.reaction_used = False


def reset_action_economy(gs: GameSession, character: Character) -> None:
    """Called at the start of every player round: fresh action/bonus/reaction
    and full movement budget.
    """
    gs.action_used = False
    gs.bonus_used = False
    gs.reaction_used = False
    gs.movement_remaining = character.speed_m or 9


def advance_round(gs: GameSession, character: Character) -> None:
    """One round = each combatant acted once. We model it loosely: after
    the player's turn has been processed (rolls + enemy_actions), bump the
    round counter and reset the player's action economy.
    """
    if not gs.combat_active:
        return
    gs.round_number = (gs.round_number or 0) + 1
    reset_action_economy(gs, character)


def format_combat_status(gs: GameSession) -> str:
    """Header line shown in the pre-narrative block during combat."""
    try:
        order = json.loads(gs.initiative_order_json or "[]")
    except Exception:
        order = []
    if not order:
        return f"⚔ Раунд {gs.round_number or 1}"
    init_line = " · ".join(f"{o['name']}({o['init']})" for o in order)
    econ = []
    if not gs.action_used:
        econ.append("действие")
    if not gs.bonus_used:
        econ.append("бонус")
    if not gs.reaction_used:
        econ.append("реакция")
    econ_line = f" | ресурсы: {', '.join(econ) or '—'}" if econ else ""
    mv = gs.movement_remaining or 0
    return f"⚔ Раунд {gs.round_number or 1} | Инициатива: {init_line} | ход: {mv}м{econ_line}"


# ─── Crafting ─────────────────────────────────────────────────────────────

@dataclass
class CraftResult:
    success: bool
    missing: list[str] = field(default_factory=list)   # "имя (нужно N, есть M)"
    roll_line: str = ""                                 # rolled skill check as text
    produced_name: str = ""                             # item added on success
    produced_quantity: int = 0
    components_consumed: list[tuple[str, int]] = field(default_factory=list)


def _match_inventory_slot(inventory: list[dict], needle: str) -> int | None:
    low = (needle or "").strip().lower()
    if not low:
        return None
    for i, item in enumerate(inventory):
        name = (item.get("name") or "").strip().lower()
        if name == low or low in name or name in low:
            return i
    return None


def attempt_craft(
    character: Character,
    recipe: dict,
    gs: GameSession | None = None,
) -> CraftResult:
    """Deterministically resolve one crafting attempt.

    Flow:
      1) Verify every component is present in inventory_json with enough qty.
      2) Roll the recipe's skill check at its DC.
      3) On success: consume components, add result to inventory. On failure:
         consume HALF of the components (rounded up) — failed crafting still
         wastes materials per TZ.
    """
    inventory = json.loads(character.inventory_json or "[]")
    required: list[tuple[str, int]] = [
        (c.get("name") or "", int(c.get("quantity", 1) or 1))
        for c in recipe.get("components", []) if c.get("name")
    ]

    missing: list[str] = []
    slot_map: dict[str, int] = {}
    for name, qty in required:
        idx = _match_inventory_slot(inventory, name)
        if idx is None or int(inventory[idx].get("quantity", 0) or 0) < qty:
            have = 0 if idx is None else int(inventory[idx].get("quantity", 0) or 0)
            missing.append(f"{name} (нужно {qty}, есть {have})")
        else:
            slot_map[name] = idx
    if missing:
        return CraftResult(success=False, missing=missing)

    skill = recipe.get("skill") or "ловкость рук"
    dc = int(recipe.get("dc") or 12)
    rich = make_skill_check(character, skill, dc, gs=gs)
    roll_line = rich.format(kind="Крафт")

    # Consume components — full on success, half (rounded up) on failure.
    consumed: list[tuple[str, int]] = []
    for name, qty in required:
        to_take = qty if rich.success else (qty + 1) // 2
        idx = slot_map[name]
        inventory[idx]["quantity"] = int(inventory[idx].get("quantity", 0)) - to_take
        consumed.append((name, to_take))
    # Drop emptied stacks.
    inventory = [i for i in inventory if int(i.get("quantity", 0) or 0) > 0]

    produced_name = ""
    produced_qty = 0
    if rich.success:
        produced_name = recipe.get("result_name") or recipe.get("name") or "Изделие"
        produced_qty = int(recipe.get("result_quantity", 1) or 1)
        new_item: dict = {
            "name": produced_name,
            "emoji": recipe.get("result_emoji", "•"),
            "type": recipe.get("result_type", "misc"),
            "quantity": produced_qty,
            "is_equipped": False,
        }
        if recipe.get("result_damage_dice"):
            new_item["damage_dice"] = recipe["result_damage_dice"]
        # Stack with existing same-name slot if possible.
        existing = _match_inventory_slot(inventory, produced_name)
        if existing is not None and inventory[existing].get("type", "misc") == new_item["type"]:
            inventory[existing]["quantity"] = (
                int(inventory[existing].get("quantity", 1) or 1) + produced_qty
            )
        else:
            inventory.append(new_item)

    character.inventory_json = json.dumps(inventory, ensure_ascii=False)
    return CraftResult(
        success=rich.success,
        missing=[],
        roll_line=roll_line,
        produced_name=produced_name,
        produced_quantity=produced_qty,
        components_consumed=consumed,
    )


def _roll_d20(advantage: bool, disadvantage: bool) -> tuple[int, int | None]:
    if advantage or disadvantage:
        a = random.randint(1, 20)
        b = random.randint(1, 20)
        if advantage and disadvantage:
            return a, None  # cancel out → single roll
        return a, b
    return random.randint(1, 20), None


def _pick_d20(d20: int, d20_alt: int | None, advantage: bool, disadvantage: bool) -> int:
    if d20_alt is None:
        return d20
    if advantage and not disadvantage:
        return max(d20, d20_alt)
    if disadvantage and not advantage:
        return min(d20, d20_alt)
    return d20
