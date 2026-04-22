export interface CharacterRoot {
  character: {
    name: string;
    race: string;
    class: string;
    level: number;
    universe: string;
    narrative_style: string;
    xp_current: number;
    xp_to_next_level: number;
    hp_current: number;
    hp_max: number;
    temp_hp: number;
    ac: number;
    speed: number;
    proficiency_bonus: number;
    gold: number;
    rest_status?: {
      short_rest_used?: boolean;
      long_rest_available?: boolean;
    };
  };
  abilities: Record<string, number>;
  skills: Array<{ name: string; proficient?: boolean }>;
  saving_throws: Record<string, boolean>;
  conditions: Array<{ name?: string; display?: string; emoji?: string; description?: string }>;
  spell_slots?: Record<string, { used: number; total: number }>;
  known_spells?: Array<{ name: string; level?: number; emoji?: string; description?: string }>;
  class_features?: Array<{ name: string; emoji?: string; description?: string }>;
  proficiencies?: {
    skills?: string[];
    saves?: string[];
    weapons?: string[];
    armor?: string[];
    tools?: string[];
    languages?: string[];
  };
  equipment?: Record<string, { name: string; emoji?: string } | null>;
  attunement?: { max?: number; items?: number[] };
  inventory?: Array<{
    name: string;
    type?: string;
    quantity?: number;
    emoji?: string;
    rarity?: string;
    is_equipped?: boolean;
    weight_kg?: number;
    description?: string;
    damage?: string;
  }>;
  known_recipes?: Array<{ name: string; emoji?: string; can_craft?: boolean }>;
  quests?: {
    active?: Array<{
      quest_id: number;
      title: string;
      is_main?: boolean;
      description?: string;
      giver?: string;
      steps?: Array<{ text: string; completed?: boolean }>;
      rewards?: { xp?: number; gold?: number };
    }>;
    completed?: Array<{ quest_id: number; title: string }>;
  };
  location?: {
    name: string;
    description?: string;
    time_of_day?: string;
    weather?: string;
    npcs?: Array<{ name: string; attitude?: string; faction?: string; is_merchant?: boolean }>;
  };
  factions?: Array<{ name: string; score: number }>;
  adventure_summary?: string;
}
