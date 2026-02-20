
import { Character } from "./types";
import { getModifier, lenientParse } from "./utils";

// --- PURE D&D MECHANICS ---

export interface RestResult {
    character: Character;
    healedAmount: number;
    hitDiceSpent: number;
    summary: string;
    success: boolean;
}

export const performLongRest = (char: Character): RestResult => {
    // 1. HP to Max
    const newHp = char.maxHp;
    
    // 2. Recover Hit Dice (50% of max, min 1)
    const recoveredDice = Math.max(1, Math.floor(char.hitDice.max / 2));
    const newHitDiceCurrent = Math.min(char.hitDice.max, char.hitDice.current + recoveredDice);

    // 3. Restore Spell Slots
    const newSpellSlots = { ...char.spellSlots };
    Object.keys(newSpellSlots).forEach(lvl => {
        if (newSpellSlots[lvl]) {
            newSpellSlots[lvl] = { 
                ...newSpellSlots[lvl], 
                current: newSpellSlots[lvl].max 
            };
        }
    });

    // 4. Reset Death Saves & Conditions
    const newDeathSaves = { successes: 0, failures: 0 };

    const updatedChar: Character = {
        ...char,
        hp: newHp,
        hitDice: { ...char.hitDice, current: newHitDiceCurrent },
        spellSlots: newSpellSlots,
        deathSaves: newDeathSaves,
        conditions: [] // Clear exhaustion/conditions roughly
    };

    return {
        character: updatedChar,
        healedAmount: char.maxHp - char.hp,
        hitDiceSpent: 0,
        summary: `HP восстановлены (${newHp}/${newHp}). Hit Dice: ${newHitDiceCurrent}/${char.hitDice.max}. Ячейки магии обновлены.`,
        success: true
    };
};

export const performShortRest = (char: Character): RestResult => {
    // Can we rest?
    if (char.hp >= char.maxHp) {
        return { character: char, healedAmount: 0, hitDiceSpent: 0, summary: "Здоровье уже полное.", success: false };
    }
    if (char.hitDice.current <= 0) {
        return { character: char, healedAmount: 0, hitDiceSpent: 0, summary: "Нет костей хитов (Hit Dice) для отдыха.", success: false };
    }

    // Roll Hit Die
    const dieFace = parseInt(char.hitDice.face.replace('1d', '')) || 8;
    const roll = Math.floor(Math.random() * dieFace) + 1;
    const conMod = getModifier(char.attributes.con);
    const heal = Math.max(0, roll + conMod);
    
    const newHp = Math.min(char.maxHp, char.hp + heal);
    const newHitDiceCurrent = char.hitDice.current - 1;

    const updatedChar: Character = {
        ...char,
        hp: newHp,
        hitDice: { ...char.hitDice, current: newHitDiceCurrent }
    };

    return {
        character: updatedChar,
        healedAmount: heal,
        hitDiceSpent: 1,
        summary: `Потрачен 1 Hit Die. Восстановлено ${heal} HP (${roll} + ${conMod} CON). Осталось Hit Dice: ${newHitDiceCurrent}.`,
        success: true
    };
};

// --- AC CALCULATION ---

export const calculateArmorClass = (char: Character): number => {
    const dexMod = getModifier(char.attributes.dex);
    
    // Default: Unarmored (10 + Dex)
    let baseAc = 10 + dexMod;
    let shieldBonus = 0;
    let hasArmor = false;

    if (char.inventory) {
        char.inventory.forEach(item => {
            if (!item.equipped) return;

            // Try to parse mechanics if they exist
            // Expected format in mechanics: { "ac": 14, "type": "medium", "bonus": 2 }
            const mechStr = typeof item.mechanics === 'string' ? item.mechanics : JSON.stringify(item.mechanics || {});
            const stats = lenientParse(mechStr) || {};

            if (item.type === 'armor') {
                // Check if it's a Shield via Name or Mechanics
                const isShield = item.name.toLowerCase().includes('shield') || 
                                 item.name.toLowerCase().includes('щит') || 
                                 stats.type === 'shield';

                if (isShield) {
                    const bonus = stats.ac || stats.bonus || 2;
                    shieldBonus += parseInt(String(bonus)) || 2;
                } 
                // Regular Armor
                else if (stats.ac) {
                    hasArmor = true;
                    const armorVal = parseInt(String(stats.ac));
                    const type = (stats.type || "").toLowerCase();

                    if (type.includes('heavy') || type.includes('тяжел')) {
                        // Heavy Armor: Flat AC, no Dex
                        baseAc = armorVal;
                    } else if (type.includes('medium') || type.includes('средн')) {
                        // Medium Armor: AC + Dex (Max 2)
                        baseAc = armorVal + Math.min(2, dexMod);
                    } else {
                        // Light or Standard: AC + Dex
                        baseAc = armorVal + dexMod;
                    }
                }
            }
        });
    }

    return baseAc + shieldBonus;
};
