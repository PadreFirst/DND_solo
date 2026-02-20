from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass
class RollResult:
    dice: str
    rolls: list[int]
    modifier: int
    total: int
    reason: str
    advantage: bool = False
    disadvantage: bool = False
    natural_20: bool = False
    natural_1: bool = False

    @property
    def display(self) -> str:
        rolls_str = ", ".join(str(r) for r in self.rolls)
        mod_str = f" {self.modifier:+d}" if self.modifier else ""
        tag = ""
        if self.natural_20:
            tag = " NAT 20!"
        elif self.natural_1:
            tag = " NAT 1!"
        return f"{self.dice}{mod_str} = [{rolls_str}]{mod_str} = {self.total}{tag}"


def _roll_die(sides: int) -> int:
    return secrets.randbelow(sides) + 1


def _sanitize_dice(raw: str) -> str:
    """Normalize a dice string, handling common AI-generated variants."""
    import re
    raw = raw.strip().lower()
    if not raw:
        return "1d4"
    m = re.search(r'(\d+)\s*d\s*(\d+)', raw)
    if m:
        return f"{m.group(1)}d{m.group(2)}"
    if raw.startswith("d") and raw[1:].isdigit():
        return f"1{raw}"
    m = re.match(r'^(\d+)$', raw)
    if m:
        return f"1d{m.group(1)}"
    return "1d4"


def roll(
    dice_str: str,
    modifier: int = 0,
    advantage: bool = False,
    disadvantage: bool = False,
    reason: str = "",
) -> RollResult:
    """Roll dice in NdM format (e.g. '2d6', '1d20', 'd8')."""
    dice_str = _sanitize_dice(dice_str)

    parts = dice_str.split("d")
    count = int(parts[0])
    sides = int(parts[1])

    if sides == 20 and count == 1 and (advantage or disadvantage):
        r1 = _roll_die(sides)
        r2 = _roll_die(sides)
        if advantage:
            chosen = max(r1, r2)
        else:
            chosen = min(r1, r2)
        total = chosen + modifier
        return RollResult(
            dice=dice_str,
            rolls=[r1, r2],
            modifier=modifier,
            total=total,
            reason=reason,
            advantage=advantage,
            disadvantage=disadvantage,
            natural_20=(chosen == 20),
            natural_1=(chosen == 1),
        )

    rolls = [_roll_die(sides) for _ in range(count)]
    total = sum(rolls) + modifier
    return RollResult(
        dice=dice_str,
        rolls=rolls,
        modifier=modifier,
        total=total,
        reason=reason,
        natural_20=(sides == 20 and count == 1 and rolls[0] == 20),
        natural_1=(sides == 20 and count == 1 and rolls[0] == 1),
    )


def roll_ability_scores() -> list[int]:
    """4d6 drop lowest, 6 times."""
    scores = []
    for _ in range(6):
        four_rolls = [_roll_die(6) for _ in range(4)]
        four_rolls.sort()
        scores.append(sum(four_rolls[1:]))
    return scores
