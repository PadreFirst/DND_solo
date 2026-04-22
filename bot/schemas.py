from __future__ import annotations

from pydantic import BaseModel, Field


class RollRequest(BaseModel):
    type: str = Field(description="skill|attack|save")
    label: str = ""
    ability: str = ""
    dc: int = 10
    advantage: bool = False
    disadvantage: bool = False
    # When type=attack, the LLM can (and should) include damage dice and a
    # target name so the engine rolls damage itself — the user wants to see
    # "сколько HP я минусую" and it must apply to a specific scene enemy.
    damage_dice: str = ""
    damage_type: str = ""  # slashing|piercing|fire|cold|lightning|poison|...
    target: str = ""
    # Social rolls: name the NPC's faction so the engine can look up the
    # player's current reputation and apply a bonus/penalty. If the NPC has
    # no faction, leave empty.
    faction: str = ""
    npc_name: str = ""


class EnemyAction(BaseModel):
    name: str = ""
    attack_bonus: int = 0
    damage_dice: str = ""
    damage_type: str = ""
    reason: str = ""


class ReputationChange(BaseModel):
    faction: str = ""
    value: int = 0


class InventoryChange(BaseModel):
    action: str = Field(default="add", description="add|remove|use")
    name: str = ""
    quantity: int = 1
    # Optional meta so new items (especially weapons picked up as loot) land
    # in the DB already annotated with their damage formula and icon.
    damage_dice: str = ""
    emoji: str = ""
    item_type: str = ""  # weapon|armor|consumable|misc|ranged|...
    weight_kg: float = 0.0
    requires_attunement: bool = False


class SceneEnemy(BaseModel):
    """A single combatant on the current scene.

    The LLM supplies this every time combat is ongoing. The engine keeps the
    list in sync (apply damage, remove dead ones) and shows it before every
    attack so the player sees enemy HP/AC up-front.
    """
    name: str = ""
    hp_current: int = 0
    hp_max: int = 0
    ac: int = 10
    notes: str = ""


class StartingItem(BaseModel):
    name: str = ""
    emoji: str = ""
    item_type: str = "misc"
    quantity: int = 1
    is_equipped: bool = False
    damage_dice: str = ""
    weight_kg: float = 0.0
    requires_attunement: bool = False


class TradeItem(BaseModel):
    """One slot inside a merchant's `trade_offer`. Price is in gold."""
    name: str = ""
    emoji: str = ""
    item_type: str = "misc"
    damage_dice: str = ""
    price: int = 0
    quantity: int = 1


class TradeOffer(BaseModel):
    """Merchant NPC pitches goods. Surfaced to the player after the narrative
    so they can decide to buy next turn. If `buys_from_player` is True the
    merchant is also interested in purchases (LLM can declare `buy_back`
    prices for items the PC owns).
    """
    npc: str = ""
    items: list[TradeItem] = Field(default_factory=list)
    buys_from_player: bool = False
    # Standard rate the NPC pays for used gear (as a fraction, e.g. 0.4 = 40%).
    buy_back_rate: float = 0.5


class RecipeComponent(BaseModel):
    name: str = ""
    quantity: int = 1


class Recipe(BaseModel):
    """Crafting recipe — stored in `Character.known_recipes_json` after being
    granted by the LLM (found in a book, taught by NPC, etc).
    """
    name: str = ""
    result_name: str = ""
    result_emoji: str = ""
    result_type: str = "misc"
    result_damage_dice: str = ""
    result_quantity: int = 1
    components: list[RecipeComponent] = Field(default_factory=list)
    skill: str = "ловкость рук"  # skill name used for the craft check
    dc: int = 12


class Ability(BaseModel):
    """A universe-agnostic active ability — could be a D&D spell, a Jedi
    Force power, a Chip'n'Dale gadget, a Shrek gingerbread man's sugar-rush,
    whatever. The engine doesn't care: it tracks charges, the LLM supplies
    the fiction + any dice.

    Refresh policy:
      "short"  — restored on a short rest
      "long"   — restored on a long rest
      "encounter" — reset on combat end
      "at_will"  — no tracking (infinite uses)
    """
    name: str = ""
    emoji: str = ""
    description: str = ""
    max_uses: int = 1
    current_uses: int = 1
    refresh: str = "long"  # short|long|encounter|at_will
    tags: list[str] = Field(default_factory=list)  # free-form: "fire", "mind", "stealth"
    # Optional dice the engine rolls when the ability is /use-d. Leaving all
    # blank means this is purely narrative — engine just spends the charge.
    damage_dice: str = ""
    damage_type: str = ""
    heal_dice: str = ""
    save_ability: str = ""  # STR|DEX|CON|INT|WIS|CHA — for save-vs-ability effects
    save_dc: int = 0


class AbilityUse(BaseModel):
    """Player triggered an ability via /use (or LLM narrated the use). Code
    rolls dice and spends the charge.
    """
    name: str = ""
    target: str = ""


class LevelUpPerk(BaseModel):
    """One option on the level-up menu. LLM proposes 3 of these tailored to
    the character's universe/concept so a jedi gets Force perks, a hobbit
    gets courage/craft perks, etc. Engine applies the effect when picked.

    effect_type values:
      "stat"        → bump one ability score by +1 or +2 (field: stat_key, stat_delta)
      "hp"          → extra HP (field: hp_delta)
      "proficiency" → gain a skill/save proficiency (field: proficiency_name)
      "ability"     → grant a new Ability (field: granted_ability)
      "feature"     → cosmetic/narrative feat (no mechanical change beyond flavor)
    """
    id: str = ""        # short slug, used in callback data
    label: str = ""     # short button caption
    description: str = ""
    effect_type: str = "feature"
    stat_key: str = ""         # STR|DEX|CON|INT|WIS|CHA
    stat_delta: int = 0
    hp_delta: int = 0
    proficiency_name: str = ""
    granted_ability: Ability | None = None


class LevelUpOffer(BaseModel):
    """Bundle of perks shown to the player after crossing an XP threshold."""
    new_level: int = 0
    flavor: str = ""   # one-line congrats in-setting
    perks: list[LevelUpPerk] = Field(default_factory=list)


class QuestStep(BaseModel):
    key: str = ""
    description: str = ""
    done: bool = False


class QuestEvent(BaseModel):
    """Structured quest event emitted by the LLM. Creates/updates/completes a
    row in the `quests` table.
    """
    action: str = "create"  # create|update|complete_step|complete|fail
    title: str = ""          # natural-language title; doubles as a lookup key
    description: str = ""
    giver: str = ""
    is_main: bool = False
    steps: list[QuestStep] = Field(default_factory=list)
    step_key_completed: str = ""  # when action=complete_step
    reward_xp: int = 0
    reward_gold: int = 0


class CompanionSpec(BaseModel):
    """A party-member NPC recruited by the player. Works in combat alongside
    the PC (rolls initiative, takes damage, can attack). Not a real human —
    just a bot-controlled ally.
    """
    name: str = ""
    role: str = ""  # short description: "лекарь", "дроид-разведчик", "пёс"
    hp_current: int = 10
    hp_max: int = 10
    ac: int = 12
    attack_bonus: int = 3
    damage_dice: str = "1d6"
    damage_type: str = ""
    initiative_bonus: int = 0
    notes: str = ""


class CharacterSetup(BaseModel):
    """LLM-generated starting stats for a new character. Only used at world
    opening. Without this the engine used to seed a generic medieval fighter,
    which is wrong in non-fantasy settings (cyberpunk → getting a long sword).
    """
    name: str = ""
    race: str = ""
    char_class: str = ""
    universe: str = ""
    narrative_style: str = ""
    abilities: dict[str, int] = Field(default_factory=dict)
    skill_proficiencies: list[str] = Field(default_factory=list)
    saving_throw_proficiencies: list[str] = Field(default_factory=list)
    starting_inventory: list[StartingItem] = Field(default_factory=list)
    starting_abilities: list[Ability] = Field(default_factory=list)


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
    # Combat scene state. `combat_active=True` + a non-empty enemy list kicks
    # the engine into the "show enemy stats first" display mode. If
    # combat_active=False or enemies=[] the scene is cleared.
    combat_active: bool = False
    scene_enemies: list[SceneEnemy] = Field(default_factory=list)
    # Used ONLY at world opening. Ignored on every other turn.
    character_setup: CharacterSetup | None = None
    # Trading: NPC merchants pitch their wares via this field. Pure display +
    # a hint to the player for the next turn ("купить пистолет за 120 золота").
    trade_offer: TradeOffer | None = None
    # Direct gold movement (buy/sell, loot purse, tips). Positive = gain.
    direct_gold_change: int = 0
    # Crafting: LLM hands the player a blueprint. Stored in
    # Character.known_recipes_json on the spot so /craft can see it.
    grant_recipe: Recipe | None = None
    # Passive perception: when set, the engine auto-checks 10+WIS+prof vs DC
    # (no d20 roll) and reveals/hides scene details accordingly. Used for
    # hidden clues, stealthed NPCs, traps the player didn't actively look
    # for. Leave 0 to skip.
    passive_perception_dc: int = 0
    passive_perception_reveal: str = ""  # narrative hint shown ONLY on success
    # Ability granted this turn (new spell learned, new Force power, etc).
    # Stored in Character.abilities_json.
    grant_ability: Ability | None = None
    # LLM can ALSO report a narrative ability-use — engine spends the charge
    # and rolls dice. Usually triggered by /use but the LLM may narrate one
    # too (e.g. NPC gift scene).
    ability_use: AbilityUse | None = None
    # Structured quest events — create/update/complete quest rows.
    quest_events: list[QuestEvent] = Field(default_factory=list)
    # Companions.
    add_companion: CompanionSpec | None = None
    remove_companion: str = ""
