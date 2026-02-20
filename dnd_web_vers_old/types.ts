
export interface SavedState {
  content: string;
  lastUpdated: number;
}

export interface SidebarButtonProps {
  label: string;
  onClick: () => void;
  isActive?: boolean;
}

// --- RPG Types ---

export type GamePhase = 'world-creation' | 'character-creation' | 'intro' | 'gameplay' | 'levelup' | 'gameover';

export interface Attributes {
  str: number;
  dex: number;
  con: number;
  int: number;
  wis: number;
  cha: number;
}

export interface InventoryItem {
  name: string;
  type: 'weapon' | 'armor' | 'consumable' | 'misc' | 'ammo';
  description?: string;
  mechanics?: string; // e.g. "Range 30ft, 1d6 Piercing"
  quantity: number;
  equipped?: boolean; // New field to track active gear
}

export interface Character {
  name: string;
  race: string;
  class: string;
  level: number;
  xp: number;
  hp: number;
  maxHp: number;
  ac: number;
  attributes: Attributes;
  inventory: InventoryItem[];
  skills: string[]; // List of proficient skills names
  savingThrows: string[]; // List of proficient attributes for saves (e.g. ['dex', 'int'])
  features: Array<{name: string, description: string}>;
  conditions: string[];
  gold: number;
  // New Mechanics
  hitDice: { current: number; max: number; face: string }; // e.g. { current: 1, max: 1, face: "1d8" }
  spellSlots: {
      [level: string]: { current: number; max: number }; // "1": {current: 2, max: 2}
  };
  deathSaves: {
      successes: number;
      failures: number;
  };
}

export interface WorldData {
  description: string;
  genre: string;
  name: string;
  currencyLabel?: string; // e.g. "Credits", "Rubles", "Gold"
  combatState?: string; // Text summary of current enemies and their status to prevent amnesia
}

export interface LogEntry {
  id: string;
  role: 'user' | 'model' | 'system' | 'roll_result';
  text: string;
  timestamp: number;
  meta?: any; 
}

export interface CheckRequest {
  attribute: string; 
  difficulty: number; 
  dice: string; 
  reason?: string; // Why is this check happening?
  successRisk?: string; // Narrative outcome on success
  failRisk: string; // Narrative outcome on failure
  isAttack?: boolean; // Is this an attack roll?
  isSave?: boolean; // Is this a saving throw?
  damageDice?: string; // e.g. "1d6" if attack
}

export interface GameState {
  phase: GamePhase;
  world: WorldData | null;
  character: Character | null;
  history: LogEntry[];
  currentOptions: string[];
  lastDiceRoll?: string;
  pendingCheck?: CheckRequest | null;
  levelUpChoices?: Array<{name: string, description: string}>;
}

export interface AIResponse {
  narrative: string;
  options: string[];
  characterUpdate?: Partial<Character>;
  worldUpdate?: Partial<WorldData>;
  isGameOver?: boolean;
  isLevelUp?: boolean;
  levelUpOptions?: Array<{name: string, description: string}>;
  validationError?: string;
  check?: CheckRequest; 
}
