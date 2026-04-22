from __future__ import annotations

import random
import re
from dataclasses import dataclass


_DICE_RE = re.compile(r"^\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


@dataclass
class RollResult:
    total: int
    detail: str
    d20_first: int | None = None
    d20_second: int | None = None
    used_advantage: bool = False
    used_disadvantage: bool = False


def roll_dice(dice: str, *, advantage: bool = False, disadvantage: bool = False) -> RollResult:
    m = _DICE_RE.match(dice)
    if not m:
        raise ValueError(f"Invalid dice expression: {dice!r}")
    count = int(m.group(1))
    sides = int(m.group(2))
    mod = int((m.group(3) or "0").replace(" ", ""))

    if count == 1 and sides == 20 and (advantage or disadvantage):
        a = random.randint(1, 20)
        b = random.randint(1, 20)
        chosen = max(a, b) if advantage and not disadvantage else min(a, b)
        if advantage and disadvantage:
            chosen = a
            advantage = False
            disadvantage = False
        total = chosen + mod
        detail = f"[{a},{b}] -> {chosen} {mod:+d}" if mod else f"[{a},{b}] -> {chosen}"
        return RollResult(
            total=total,
            detail=detail,
            d20_first=a,
            d20_second=b,
            used_advantage=advantage,
            used_disadvantage=disadvantage,
        )

    rolls = [random.randint(1, sides) for _ in range(count)]
    base = sum(rolls)
    total = base + mod
    detail = f"{rolls} {mod:+d}" if mod else f"{rolls}"
    return RollResult(total=total, detail=detail)
