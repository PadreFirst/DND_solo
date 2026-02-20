
import { Attributes, Character, AIResponse, InventoryItem, CheckRequest } from "./types";
import { SKILL_MAP } from "./constants";

// Helper to safely render potential objects as strings
export const safeRender = (value: any): string => {
    if (typeof value === 'string') return value;
    if (typeof value === 'number') return String(value);
    if (typeof value === 'object' && value !== null) {
        if (value.text) return String(value.text);
        if (value.current) return String(value.current);
        return JSON.stringify(value);
    }
    return '';
};

// --- DATA COERCION & VALIDATION ---

const coerceNumber = (val: any, fallback?: number): number | undefined => {
    if (val === undefined || val === null) return fallback;
    if (typeof val === 'number') return isNaN(val) ? fallback : val;
    if (typeof val === 'string') {
        const parsed = parseFloat(val);
        return isNaN(parsed) ? fallback : parsed;
    }
    return fallback;
};

const coerceString = (val: any, fallback: string = ""): string => {
    if (val === undefined || val === null) return fallback;
    if (typeof val === 'string') return val;
    return String(val);
};

const normalizeInventory = (rawItems: any[]): InventoryItem[] => {
    if (!Array.isArray(rawItems)) return [];
    return rawItems.map((item: any) => ({
        name: coerceString(item.name, "Unknown Item"),
        type: (['weapon', 'armor', 'consumable', 'misc', 'ammo'].includes(item.type) ? item.type : 'misc') as any,
        description: item.description ? coerceString(item.description) : undefined,
        mechanics: item.mechanics, // Keep as is, flexible
        quantity: coerceNumber(item.quantity, 1) || 1,
        equipped: !!item.equipped
    }));
};

const normalizeAttributes = (rawAttrs: any): Partial<Attributes> | undefined => {
    if (!rawAttrs || typeof rawAttrs !== 'object') return undefined;
    const res: any = {};
    ['str', 'dex', 'con', 'int', 'wis', 'cha'].forEach(key => {
        if (rawAttrs[key] !== undefined) {
            res[key] = coerceNumber(rawAttrs[key], 10);
        }
    });
    return res;
};

const normalizeCheck = (rawCheck: any): CheckRequest | undefined => {
    if (!rawCheck || typeof rawCheck !== 'object') return undefined;
    return {
        attribute: coerceString(rawCheck.attribute, 'dex'),
        difficulty: coerceNumber(rawCheck.difficulty, 10) || 10,
        dice: coerceString(rawCheck.dice, '1d20'),
        reason: coerceString(rawCheck.reason, 'Check'),
        successRisk: coerceString(rawCheck.successRisk, 'Success'),
        failRisk: coerceString(rawCheck.failRisk, 'Failure'),
        isAttack: !!rawCheck.isAttack,
        isSave: !!rawCheck.isSave,
        damageDice: rawCheck.damageDice ? coerceString(rawCheck.damageDice) : undefined
    };
};

/**
 * Acts as a Schema Validator (Zod-like).
 * Ensures the AI response strictly adheres to the expected types,
 * preventing crashes when AI returns "10" (string) instead of 10 (number).
 */
export const normalizeAIResponse = (raw: any): AIResponse => {
    // 1. Basic Structure
    if (!raw || typeof raw !== 'object') {
        return { 
            narrative: "Error: AI returned invalid data structure.", 
            options: ["Retry"] 
        };
    }

    const response: AIResponse = {
        narrative: coerceString(raw.narrative, "..."),
        options: Array.isArray(raw.options) ? raw.options.map((o: any) => coerceString(o)) : [],
        isGameOver: !!raw.isGameOver,
        isLevelUp: !!raw.isLevelUp,
        validationError: raw.validationError ? coerceString(raw.validationError) : undefined
    };

    // 2. Character Update Sanitization
    if (raw.characterUpdate && typeof raw.characterUpdate === 'object') {
        const c = raw.characterUpdate;
        const cleanChar: Partial<Character> = {};

        if (c.name !== undefined) cleanChar.name = coerceString(c.name);
        if (c.race !== undefined) cleanChar.race = coerceString(c.race);
        if (c.class !== undefined) cleanChar.class = coerceString(c.class);
        
        // Coerce Numbers (String -> Number) with safety floors
        // SAFETY: HP must be at least 1 to prevent immediate death loop on generation
        if (c.hp !== undefined) {
             const val = coerceNumber(c.hp, 1);
             cleanChar.hp = val !== undefined ? Math.max(1, val) : 1; 
        }
        if (c.maxHp !== undefined) {
             const val = coerceNumber(c.maxHp, 1);
             cleanChar.maxHp = val !== undefined ? Math.max(1, val) : 1;
        }
        
        if (c.ac !== undefined) cleanChar.ac = coerceNumber(c.ac);
        
        // Ensure gold is treated as number, allow 0
        if (c.gold !== undefined) cleanChar.gold = coerceNumber(c.gold, 0);
        
        if (c.level !== undefined) cleanChar.level = coerceNumber(c.level);
        if (c.xp !== undefined) cleanChar.xp = coerceNumber(c.xp);

        // Arrays & Objects
        if (c.attributes) cleanChar.attributes = normalizeAttributes(c.attributes) as any;
        
        // INVENTORY & AMMO CHECK LOGIC
        if (c.inventory) {
            cleanChar.inventory = normalizeInventory(c.inventory);
            
            // Hard logic: Ensure ammo exists if ranged weapon exists
            const hasRanged = cleanChar.inventory.some(i => {
                const n = i.name.toLowerCase();
                return n.includes('bow') || n.includes('лук') || 
                       n.includes('gun') || n.includes('rifle') || n.includes('pistol') || n.includes('пистолет') || n.includes('винтовка') ||
                       n.includes('crossbow') || n.includes('арбалет');
            });

            const hasAmmo = cleanChar.inventory.some(i => i.type === 'ammo' || i.name.toLowerCase().includes('ammo') || i.name.toLowerCase().includes('патрон') || i.name.toLowerCase().includes('стрел'));

            if (hasRanged && !hasAmmo) {
                cleanChar.inventory.push({
                    name: "Комплект боеприпасов",
                    type: "ammo",
                    quantity: 20,
                    description: "Базовый боезапас, добавленный системой."
                });
            }
        }

        if (c.conditions && Array.isArray(c.conditions)) cleanChar.conditions = c.conditions.map((s:any) => coerceString(s));
        if (c.skills && Array.isArray(c.skills)) cleanChar.skills = c.skills.map((s:any) => coerceString(s));
        if (c.savingThrows && Array.isArray(c.savingThrows)) cleanChar.savingThrows = c.savingThrows.map((s:any) => coerceString(s));
        
        if (c.features && Array.isArray(c.features)) {
            cleanChar.features = c.features.map((f: any) => ({
                name: typeof f === 'string' ? f : coerceString(f.name, "Unknown"),
                description: typeof f === 'string' ? "" : coerceString(f.description, "")
            }));
        }
        
        // Complex Objects
        if (c.hitDice) {
            cleanChar.hitDice = {
                current: coerceNumber(c.hitDice.current, 1)!,
                max: coerceNumber(c.hitDice.max, 1)!,
                face: coerceString(c.hitDice.face, "1d8")
            };
        }
        
        if (c.deathSaves) {
            cleanChar.deathSaves = {
                successes: coerceNumber(c.deathSaves.successes, 0)!,
                failures: coerceNumber(c.deathSaves.failures, 0)!
            };
        }

        if (c.spellSlots && typeof c.spellSlots === 'object') {
            const slots: any = {};
            Object.entries(c.spellSlots).forEach(([lvl, val]: [string, any]) => {
                if (val && typeof val === 'object') {
                    slots[lvl] = {
                        current: coerceNumber(val.current, 0),
                        max: coerceNumber(val.max, 0)
                    };
                }
            });
            cleanChar.spellSlots = slots;
        }

        response.characterUpdate = cleanChar;
    }

    // 3. World Update
    if (raw.worldUpdate && typeof raw.worldUpdate === 'object') {
        const w = raw.worldUpdate;
        response.worldUpdate = {
            name: w.name ? coerceString(w.name) : undefined,
            genre: w.genre ? coerceString(w.genre) : undefined,
            description: w.description ? coerceString(w.description) : undefined,
            currencyLabel: w.currencyLabel ? coerceString(w.currencyLabel) : undefined,
            combatState: w.combatState ? coerceString(w.combatState) : undefined,
        };
    }

    // 4. Check Request
    if (raw.check) {
        response.check = normalizeCheck(raw.check);
    }

    // 5. Level Up Options
    if (raw.levelUpOptions && Array.isArray(raw.levelUpOptions)) {
        response.levelUpOptions = raw.levelUpOptions.map((opt: any) => ({
            name: coerceString(opt.name),
            description: coerceString(opt.description)
        }));
    }

    return response;
};

// --- DICE & GAME LOGIC ---

// Dice Roller Parser (e.g. "2d6" -> 7)
export const parseAndRoll = (diceString: string = "1d20"): number => {
    try {
        if (!diceString || typeof diceString !== 'string') return Math.floor(Math.random() * 20) + 1;
        
        // Handle "1d6 + 2" format roughly
        const clean = diceString.toLowerCase().replace(/\s/g, '');
        const parts = clean.split('+');
        const dicePart = parts[0];
        const flatBonus = parts.length > 1 ? parseInt(parts[1]) : 0;

        const [count, faces] = dicePart.split('d').map(Number);
        if (!count || !faces) return Math.floor(Math.random() * 20) + 1;
        
        let total = 0;
        for(let i = 0; i < count; i++) {
            total += Math.floor(Math.random() * faces) + 1;
        }
        return total + flatBonus;
    } catch {
        return Math.floor(Math.random() * 20) + 1;
    }
};

export const getModifier = (score: number) => Math.floor((score - 10) / 2);

export const getProficiencyBonus = (level: number) => Math.floor((level - 1) / 4) + 2;

// Auto-detect attribute from check name
export const resolveAttributeFromCheck = (checkName: any): keyof Attributes => {
    if (!checkName || typeof checkName !== 'string') return 'dex'; // Fallback

    const checkNameLower = checkName.toLowerCase().trim();
    
    // 1. Strict Code Match (Priority)
    if (checkNameLower === 'str') return 'str';
    if (checkNameLower === 'dex') return 'dex';
    if (checkNameLower === 'con') return 'con';
    if (checkNameLower === 'int') return 'int';
    if (checkNameLower === 'wis') return 'wis';
    if (checkNameLower === 'cha') return 'cha';

    // 2. Russian Full Names
    if (checkNameLower.includes('сила')) return 'str';
    if (checkNameLower.includes('ловкость')) return 'dex';
    if (checkNameLower.includes('тело') || checkNameLower.includes('вынос')) return 'con';
    if (checkNameLower.includes('интеллект')) return 'int';
    if (checkNameLower.includes('мудрость')) return 'wis';
    if (checkNameLower.includes('харизма')) return 'cha';
    
    // 3. Skill Mapping
    for (const [skill, attr] of Object.entries(SKILL_MAP)) {
        if (checkNameLower.includes(skill)) {
            return attr;
        }
    }
    
    // 4. Fallbacks for attacks
    if (checkNameLower.includes('attack') || checkNameLower.includes('атака')) {
        return 'dex'; 
    }

    return 'dex'; 
};

export const isSavingThrow = (checkName: string): boolean => {
    if (!checkName) return false;
    const lower = checkName.toLowerCase();
    return lower.includes('save') || lower.includes('спас') || lower.includes('saving');
};

// Lenient JSON parser for AI outputs
export const lenientParse = (str: string): any => {
    try {
        return JSON.parse(str);
    } catch (e) {
        try {
            // Try replacing single quotes with double quotes
            const fixed = str.replace(/'/g, '"');
            return JSON.parse(fixed);
        } catch (e2) {
            return null;
        }
    }
};
