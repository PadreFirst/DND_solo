from __future__ import annotations

from pydantic import BaseModel, Field


class RollRequest(BaseModel):
    type: str = Field(description="skill|attack|save")
    label: str = ""
    ability: str = ""
    dc: int = 10
    advantage: bool = False
    disadvantage: bool = False


class EnemyAction(BaseModel):
    name: str = ""
    attack_bonus: int = 0
    damage_dice: str = ""
    reason: str = ""


class ReputationChange(BaseModel):
    faction: str = ""
    value: int = 0


class InventoryChange(BaseModel):
    action: str = Field(default="add", description="add|remove|use")
    name: str = ""
    quantity: int = 1


class TurnPlan(BaseModel):
    narrative: str = ""
    gm_question_mode: bool = False
    gm_answer: str = ""
    rolls: list[RollRequest] = Field(default_factory=list)
    enemy_actions: list[EnemyAction] = Field(default_factory=list)
    direct_hp_change: int = 0
    inventory_changes: list[InventoryChange] = Field(default_factory=list)
    location_name: str = ""
    location_description: str = ""
    quest_update: str = ""
    xp_award: int = 0
    reputation_change: list[ReputationChange] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
