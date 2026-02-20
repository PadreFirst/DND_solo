
import { useState, useEffect, useRef, useCallback } from 'react';
import { GoogleGenAI } from '@google/genai';
import { usePersistentState } from './usePersistentState';
import { GameState, Character, AIResponse, LogEntry, CheckRequest } from '../types';
import { AI_MODEL_ID, INITIAL_GAME_STATE, DUMMY_CHAR } from '../constants';
import { parseAndRoll, getModifier, resolveAttributeFromCheck, isSavingThrow, getProficiencyBonus, normalizeAIResponse } from '../utils';
import { performLongRest, performShortRest, calculateArmorClass } from '../gameRules';

interface UseGameEngineReturn {
    state: GameState;
    ui: {
        input: string;
        isLoading: boolean;
        error: string | null;
        isRolling: boolean;
        rollAnimValue: number;
        showHelp: boolean;
        helpText: string;
    };
    actions: {
        setInput: (s: string) => void;
        handleAction: (text: string) => Promise<void>;
        handleNextPhase: () => void;
        handleStartIntro: () => void;
        handleHelp: () => Promise<void>;
        handleInspect: () => Promise<void>;
        handleRest: (type: 'short' | 'long') => void;
        handleToggleEquip: (index: number) => void;
        handleRoll: (type?: 'normal' | 'adv' | 'dis') => void;
        handleDamageRoll: (entryIndex: number, diceString: string) => void;
        setShowHelp: (b: boolean) => void;
    };
}

export const useGameEngine = (storageKey: string, prompts: any): UseGameEngineReturn => {
    const { text: jsonState, setText: setJsonState } = usePersistentState(storageKey, JSON.stringify(INITIAL_GAME_STATE));
    
    // Core Game State
    const [state, setState] = useState<GameState>(INITIAL_GAME_STATE);
    const stateRef = useRef(state);
    
    // UI State
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isRolling, setIsRolling] = useState(false);
    const [rollAnimValue, setRollAnimValue] = useState(0);
    const [showHelp, setShowHelp] = useState(false);
    const [helpText, setHelpText] = useState('');
    
    const introTriggered = useRef(false);

    // Sync State Ref
    useEffect(() => {
        stateRef.current = state;
    }, [state]);

    // Initial Load
    useEffect(() => {
        try {
            const parsed = JSON.parse(jsonState);
            const merged = { ...INITIAL_GAME_STATE, ...parsed };
            if (merged.character && !merged.character.deathSaves) {
                merged.character.deathSaves = { successes: 0, failures: 0 };
            }
            setState(merged);
        } catch (e) {
            setState(INITIAL_GAME_STATE);
        }
    }, [jsonState]);

    const saveState = (newState: GameState) => {
        setState(newState);
        setJsonState(JSON.stringify(newState));
    };

    // --- AI ENGINE ---
    const callAI = async (prompt: string, isHelpRequest: boolean = false, isRollResult: boolean = false, injectedHistory: LogEntry[] | null = null) => {
        setIsLoading(true);
        setError(null);
        
        const currentState = stateRef.current;

        try {
            if (!process.env.API_KEY) throw new Error("API Key missing");
            const ai = new GoogleGenAI({ apiKey: process.env.API_KEY });
            
            let baseInstruction = "";
            if (currentState.phase === 'world-creation') baseInstruction = prompts.worldGen;
            else if (currentState.phase === 'character-creation') baseInstruction = prompts.charGen;
            else baseInstruction = prompts.gameplay;

            const systemInstruction = `
            ${baseInstruction}
            ВАЖНО: ОТВЕЧАЙ СТРОГО В JSON.
            `;

            const historySource = injectedHistory || currentState.history;

            // Load Chat History (User/Model turns)
            const historyContext = historySource
                .filter(h => h.role !== 'roll_result' && h.role !== 'system') 
                .slice(-15) // Limit history context
                .map(h => ({ 
                    role: h.role === 'model' ? 'model' : 'user', 
                    parts: [{ text: h.text ? String(h.text) : " " }] 
                }));

            // --- STATE INJECTION STRATEGY ---
            let activePrompt = prompt;
            
            if (currentState.phase === 'gameplay' || currentState.phase === 'intro' || currentState.phase === 'levelup') {
                 const char = currentState.character || DUMMY_CHAR;
                 const world = currentState.world || { name: '', genre: '', combatState: '' };

                 // 1. Snapshot Current State from React (Single Source of Truth)
                 const playerState = {
                     hp: `${char.hp}/${char.maxHp}`,
                     ac: char.ac,
                     attributes: char.attributes,
                     // mechanics field contains damage info etc.
                     equipped: char.inventory.filter(i => i.equipped).map(i => `${i.name} ${i.mechanics ? `(${JSON.stringify(i.mechanics)})` : ''}`),
                     spellSlots: char.spellSlots,
                     gold: char.gold,
                     conditions: char.conditions,
                     inventory: char.inventory.map(i => `${i.name} (x${i.quantity})`)
                 };

                 const worldState = {
                     name: world.name,
                     genre: world.genre,
                     enemies: world.combatState || "None",
                     activePhase: currentState.phase
                 };

                 // 2. Wrap User Action
                 activePrompt = `
[SYSTEM INFO]
Current Player State: ${JSON.stringify(playerState)}
Current World State: ${JSON.stringify(worldState)}

[USER ACTION]
"${prompt}"
                 `;
            } else if (currentState.phase === 'character-creation') {
                 // SPECIAL CASE: Inject World Info so AI knows what items to generate
                 const world = currentState.world || { name: 'Unknown', genre: 'Fantasy', description: '' };
                 activePrompt = `
[WORLD CONTEXT]
Name: ${world.name}
Genre: ${world.genre}
Description: ${world.description}

[USER CHARACTER REQUEST]
"${prompt}"
                 `;
            }

            const finalContents = [...historyContext];
            
            // Add the formatted active prompt
            finalContents.push({ role: 'user', parts: [{ text: activePrompt }] });

            // Retry Logic
            let response: any = null;
            let attempt = 0;
            const maxRetries = 3;

            while (attempt < maxRetries) {
                try {
                    response = await ai.models.generateContent({
                        model: AI_MODEL_ID,
                        contents: finalContents,
                        config: {
                            systemInstruction: systemInstruction,
                            responseMimeType: "application/json",
                            temperature: 0.7
                        }
                    });
                    break;
                } catch (e: any) {
                    const msg = (e.message || JSON.stringify(e)).toLowerCase();
                    const isQuota = msg.includes("429") || msg.includes("resource_exhausted") || msg.includes("quota");
                    
                    if (isQuota && attempt < maxRetries - 1) {
                        attempt++;
                        const delay = 2000 * Math.pow(2, attempt);
                        console.warn(`Quota hit (429), retrying in ${delay}ms...`);
                        await new Promise(r => setTimeout(r, delay));
                        continue;
                    }
                    throw e;
                }
            }

            if (!response) throw new Error("No response from AI");

            // --- ROBUST JSON EXTRACTION ---
            let textResponse = response.text || "{}";
            
            // 1. Strip Markdown code blocks (```json ... ```)
            textResponse = textResponse.replace(/```json/g, '').replace(/```/g, '');
            
            // 2. Find outer braces to handle any header/footer text
            const firstBrace = textResponse.indexOf('{');
            const lastBrace = textResponse.lastIndexOf('}');
            
            if (firstBrace !== -1 && lastBrace !== -1) {
                textResponse = textResponse.substring(firstBrace, lastBrace + 1);
            }
            
            const rawJson = JSON.parse(textResponse);
            
            // VALIDATION LAYER: Coerce types and safe-guard against crashes
            const jsonResponse = normalizeAIResponse(rawJson);

            if (jsonResponse.validationError) {
                setError(jsonResponse.validationError);
                setIsLoading(false);
                return;
            }

            if (isHelpRequest) {
                setHelpText(jsonResponse.narrative);
                setShowHelp(true);
                setIsLoading(false);
                return;
            }

            const newState = { ...stateRef.current };
            if (injectedHistory) {
                newState.history = injectedHistory;
            }
            
            if (jsonResponse.worldUpdate) newState.world = { ...(newState.world || {description: '', genre: '', name: ''}), ...jsonResponse.worldUpdate };
            
            // PHASE MANAGEMENT
            let justFinishedCharCreation = false;

            if (jsonResponse.characterUpdate) {
                const oldChar = newState.character || DUMMY_CHAR;
                const update = jsonResponse.characterUpdate;

                // Incoming Damage Detection
                if (update.hp !== undefined && oldChar.hp !== undefined && update.hp < oldChar.hp) {
                    const dmg = oldChar.hp - update.hp;
                    newState.history.push({
                        id: Date.now().toString() + "_dmg",
                        role: "system",
                        text: `💔 ПОЛУЧЕН УРОН: -${dmg} HP`,
                        timestamp: Date.now()
                    });
                }

                let mergedInventory = [...(oldChar.inventory || [])];
                if (update.inventory && Array.isArray(update.inventory)) {
                     // Check if this is character creation (starter kit) - replace instead of merge?
                     // Actually, merge is safer, but if array comes full from AI, we respect it.
                     update.inventory.forEach(newItem => {
                         if (!newItem || !newItem.name) return;
                         const existingIndex = mergedInventory.findIndex(
                             old => old.name.trim().toLowerCase() === newItem.name.trim().toLowerCase()
                         );
                         if (existingIndex >= 0) {
                             mergedInventory[existingIndex] = {
                                 ...mergedInventory[existingIndex],
                                 ...newItem,
                                 equipped: newItem.equipped !== undefined ? newItem.equipped : mergedInventory[existingIndex].equipped
                             };
                         } else {
                             mergedInventory.push(newItem);
                         }
                     });
                     mergedInventory = mergedInventory.filter(item => (item.quantity ?? 1) > 0);
                }
                
                const mergedAttributes = { ...oldChar.attributes, ...(update.attributes || {}) };
                const mergedDeathSaves = { ...(oldChar.deathSaves || {successes: 0, failures: 0}), ...(update.deathSaves || {}) };

                newState.character = {
                    ...oldChar,
                    ...update,
                    attributes: mergedAttributes,
                    gold: update.gold !== undefined ? update.gold : oldChar.gold,
                    inventory: mergedInventory,
                    deathSaves: mergedDeathSaves
                };

                // HARD LOGIC: Force Recalculate AC based on inventory to prevent AI errors
                newState.character.ac = calculateArmorClass(newState.character);
            }
            
            if (currentState.phase === 'world-creation') newState.phase = 'character-creation';
            else if (currentState.phase === 'character-creation') {
                newState.phase = 'intro';
                justFinishedCharCreation = true;
            }
            else if (currentState.phase === 'intro') newState.phase = 'gameplay';
            
            if (jsonResponse.isLevelUp) newState.phase = 'levelup';
            if (jsonResponse.isGameOver) newState.phase = 'gameover';

            if (currentState.phase === 'levelup' && !jsonResponse.isLevelUp) {
                newState.phase = 'gameplay';
            }

            // SAFETY NET: Force Level Up if XP is high enough (Level 1 -> 2 at 300XP)
            if (newState.character && newState.character.level === 1 && (newState.character.xp || 0) >= 300) {
                newState.phase = 'levelup';
            }

            const narrativeText = jsonResponse.narrative || (currentState.phase === 'intro' ? "Мир обретает форму..." : "...");

            newState.history.push({ 
                id: Date.now().toString(), 
                role: 'model', 
                text: narrativeText, 
                timestamp: Date.now() 
            });
            
            if (jsonResponse.check) {
                newState.pendingCheck = jsonResponse.check;
                newState.currentOptions = [];
            } else {
                newState.pendingCheck = null;
                if ((!jsonResponse.options || jsonResponse.options.length === 0) && newState.phase === 'gameplay') {
                    newState.currentOptions = ["Продолжить...", "Осмотреться", "Задать вопрос"];
                } else {
                    newState.currentOptions = jsonResponse.options || [];
                }
            }

            if (jsonResponse.levelUpOptions) newState.levelUpChoices = jsonResponse.levelUpOptions;

            saveState(newState);
            setInput('');

            // AUTOMATIC INTRO TRIGGER
            if (justFinishedCharCreation) {
                introTriggered.current = true;
                setTimeout(() => {
                    callAI("ВНИМАНИЕ: Персонаж создан. НАЧИНАЙ ПРИКЛЮЧЕНИЕ. Опиши стартовую локацию, атмосферу и дай первый сюжетный крюк. Не спрашивай ничего, просто погружай в игру.", false, false, newState.history);
                }, 200);
            }

        } catch (err: any) {
            console.error(err);
            introTriggered.current = false;
            const msg = (err.message || JSON.stringify(err)).toLowerCase();
            if (msg.includes("429") || msg.includes("resource_exhausted") || msg.includes("quota")) {
                 setError("⏳ Лимит запросов исчерпан (429). Подождите 60 секунд и повторите.");
            } else if (msg.includes("400")) {
                 setError("Ошибка данных запроса (400).");
            } else if (msg.includes("json")) {
                 setError("Ошибка обработки ответа нейросети (JSON).");
            } else {
                 setError("Ошибка связи с нейросетью. Попробуйте еще раз.");
            }
        } finally {
            setIsLoading(false);
        }
    };

    // --- ACTIONS ---

    const handleAction = async (text: string) => {
        if (!text.trim()) return;

        const newEntry: LogEntry = { 
            id: Date.now().toString(), 
            role: 'user', 
            text: text, 
            timestamp: Date.now() 
        };

        const newHistory = [...state.history, newEntry];
        const tempState = { ...state, history: newHistory };
        setState(tempState);
        setJsonState(JSON.stringify(tempState));

        await callAI(text, false, false, newHistory);
    };

    const handleNextPhase = () => handleAction(input || "Сгенерируй автоматически.");
    const handleStartIntro = () => callAI('Start Intro');
    const handleHelp = async () => await callAI("Мне нужна подсказка по механике или совет по ситуации.", true);
    const handleInspect = async () => handleAction("ОСМОТР: Дай тактическую оценку. Угрозы (AC, HP, Оружие), Интересные предметы, Пути отхода. Без лишней воды.");

    const handleRest = (type: 'short' | 'long') => {
        const char = state.character;
        if (!char) return;

        // Uses PURE function from gameRules.ts
        const result = type === 'long' ? performLongRest(char) : performShortRest(char);
        
        const logText = `[SYSTEM]: ${result.summary}`;
        const newHistory = [
            ...state.history,
            { id: Date.now().toString(), role: 'system' as const, text: logText, timestamp: Date.now() }
        ];

        // Update State
        const newState = {
            ...state,
            history: newHistory,
            character: result.character
        };
        saveState(newState);

        if (result.success) {
            const prompt = type === 'long' 
                ? "Прошел Длинный Отдых. Опиши спокойное утро, смену погоды и готовность героя к пути. Не меняй статы, они уже обновлены."
                : `Герой сделал передышку. Восстановил ${result.healedAmount} HP. Опиши краткий привал.`;
            
            callAI(prompt, false, false, newHistory);
        }
    };

    const handleToggleEquip = (itemIndex: number) => {
        const char = state.character;
        if (!char || !char.inventory) return;
        
        const newInventory = [...char.inventory];
        const targetItem = newInventory[itemIndex];

        // If armor (not shield) is being equipped, unequip all other armor (not shield)
        if (targetItem.type === 'armor' && !targetItem.equipped) {
             const isShield = targetItem.name.toLowerCase().includes('shield') || targetItem.name.toLowerCase().includes('щит');
             if (!isShield) {
                 newInventory.forEach(i => {
                     const iShield = i.name.toLowerCase().includes('shield') || i.name.toLowerCase().includes('щит');
                     if (i.type === 'armor' && !iShield) {
                         i.equipped = false;
                     }
                 });
             }
        }
        
        targetItem.equipped = !targetItem.equipped;
        newInventory[itemIndex] = targetItem;
        
        // Recalculate AC immediately using hard logic
        const tempChar = { ...char, inventory: newInventory };
        const newAc = calculateArmorClass(tempChar);
        const updatedChar = { ...tempChar, ac: newAc };

        const newState = {
            ...state,
            character: updatedChar
        };
        saveState(newState);
    };

    // --- DICE MECHANICS ---

    const handleDamageRoll = (entryIndex: number, diceString: string) => {
        setIsRolling(true);
        setTimeout(() => {
            const damage = parseAndRoll(diceString);
            
            const newHistory = [...stateRef.current.history];
            const entry = newHistory[entryIndex];
            
            if (entry && entry.meta) {
                 entry.meta.damageValue = damage;
                 const damageMsg = `[SYSTEM]: Player dealt ${damage} damage (${diceString}).`;
                 
                 const newState = { ...stateRef.current, history: newHistory };
                 setState(newState);
                 setJsonState(JSON.stringify(newState));
                 setIsRolling(false);
                 
                 setTimeout(() => {
                     callAI(damageMsg, false, true, newHistory);
                 }, 500);
            }
        }, 1000);
    };

    const handleRoll = (rollType: 'normal' | 'adv' | 'dis' = 'normal') => {
        const currentState = stateRef.current;
        if (!currentState.pendingCheck) return;
        
        setIsRolling(true);
        const check = currentState.pendingCheck;
        const diceConfig = check.dice || "1d20";
        const dc = check.difficulty || 10;
        const isDeathSave = check.reason?.toLowerCase().includes("death") || check.reason?.toLowerCase().includes("смерть");
        const attrKey = resolveAttributeFromCheck(check.attribute);
        const attrValue = currentState.character?.attributes?.[attrKey] || 10;
        let mod = isDeathSave ? 0 : getModifier(attrValue); 
        
        if (!isDeathSave) {
            let isProficient = false;
            const isSave = check.isSave || isSavingThrow(check.reason || "") || isSavingThrow(check.attribute);
            if (isSave) {
                isProficient = currentState.character?.savingThrows?.some(s => s.toLowerCase().includes(attrKey)) || false;
            } else {
                const checkReasonLower = (check.reason || "").toLowerCase();
                const checkAttrLower = (check.attribute || "").toLowerCase();
                if (currentState.character?.skills) {
                    isProficient = currentState.character.skills.some(skillName => {
                        const s = skillName.toLowerCase();
                        return checkReasonLower.includes(s) || checkAttrLower.includes(s);
                    });
                }
            }

            if (isProficient) {
                const pb = getProficiencyBonus(currentState.character?.level || 1);
                mod += pb;
            }
        }

        const interval = setInterval(() => {
            setRollAnimValue(Math.floor(Math.random() * 20) + 1);
        }, 80);

        setTimeout(() => {
            clearInterval(interval);
            
            try {
                // FIXED LOGIC START
                const r1 = parseAndRoll(diceConfig);
                const r2 = parseAndRoll(diceConfig);
                let finalRoll = r1;
                let recordedRolls = [r1]; // Default normal: only 1 die recorded

                if (rollType === 'adv') {
                    finalRoll = Math.max(r1, r2);
                    recordedRolls = [r1, r2];
                } else if (rollType === 'dis') {
                    finalRoll = Math.min(r1, r2);
                    recordedRolls = [r1, r2];
                }
                // FIXED LOGIC END

                const totalRoll = finalRoll + mod;
                setRollAnimValue(finalRoll); 
                setIsRolling(false);
                
                if (!stateRef.current.pendingCheck) {
                     setError("Ошибка: данные проверки потеряны.");
                     return;
                }

                const success = totalRoll >= dc;
                let resultText = "";
                const rollTypeLabel = rollType === 'adv' ? 'with ADVANTAGE' : rollType === 'dis' ? 'with DISADVANTAGE' : 'NORMAL';

                let updatedChar = { ...currentState.character } as Character;
                let isDead = false;

                if (isDeathSave && updatedChar.deathSaves) {
                    if (success) {
                         // On nat 20 (roll 20), regain 1 HP
                         if (finalRoll === 20) {
                             updatedChar.hp = 1;
                             updatedChar.deathSaves = { successes: 0, failures: 0 };
                             resultText = `[SYSTEM]: CRITICAL SUCCESS! You regain consciousness with 1 HP.`;
                         } else {
                             updatedChar.deathSaves.successes = Math.min(3, updatedChar.deathSaves.successes + 1);
                         }
                    } else {
                         // On nat 1 (roll 1), 2 failures
                         const failCount = finalRoll === 1 ? 2 : 1;
                         updatedChar.deathSaves.failures = Math.min(3, updatedChar.deathSaves.failures + failCount);
                    }

                    // HARD LOGIC: Death Enforcement (Immediate Game Over on 3 failures)
                    if (updatedChar.deathSaves.failures >= 3) {
                        isDead = true;
                        resultText = `[SYSTEM]: DEATH SAVE FAILURE. You have succumbed to your wounds. GAME OVER.`;
                    }
                }

                if (!isDead && !resultText) {
                    if (check.isAttack && success) {
                        resultText = `[SYSTEM]: ATTACK ROLL (${rollTypeLabel}). Roll ${finalRoll} + Mod ${mod} = ${totalRoll} vs AC ${dc}. HIT! Waiting for damage roll...`;
                    } else if (isDeathSave) {
                        const ds = updatedChar.deathSaves;
                        resultText = `[SYSTEM]: DEATH SAVE. Result: ${success ? "SUCCESS" : "FAILURE"}. Current Status: ${ds?.successes} Successes, ${ds?.failures} Failures.`;
                    } else {
                        resultText = `[SYSTEM]: CHECK/SAVE. Roll ${finalRoll} + Mod ${mod} = ${totalRoll} vs DC ${dc}. Result: ${success ? 'SUCCESS' : 'FAILURE'}.`;
                    }
                }

                const visualEntry: LogEntry = {
                    id: Date.now().toString(),
                    role: 'roll_result',
                    text: success ? "УСПЕХ" : "ПРОВАЛ",
                    timestamp: Date.now(),
                    meta: {
                        roll: finalRoll, rolls: recordedRolls, mod: mod, total: totalRoll, dc: dc,
                        attr: isDeathSave ? "DEATH" : attrKey.toUpperCase(),
                        success: success, reason: check.reason, dice: diceConfig,
                        isAttack: check.isAttack,
                        damageDice: check.isAttack && success ? (check.damageDice || "1d4") : null,
                        successLabel: check.successRisk || "Успех", failLabel: check.failRisk || "Провал",
                        rollType: rollType // Ensure this is saved exactly as passed
                    }
                };
                
                const newHistory = [...stateRef.current.history, visualEntry];
                if (isDead) {
                    newHistory.push({
                         id: Date.now().toString() + "_death",
                         role: "system",
                         text: "💀 ПЕРСОНАЖ ПОГИБ. ИСТОРИЯ ЗАВЕРШЕНА.",
                         timestamp: Date.now()
                    });
                }

                const stateAfterRoll = { 
                    ...stateRef.current, 
                    history: newHistory, 
                    pendingCheck: null,
                    character: updatedChar,
                    phase: isDead ? 'gameover' : stateRef.current.phase
                } as GameState;

                setState(stateAfterRoll);
                setJsonState(JSON.stringify(stateAfterRoll));

                // Only call AI if not attack (waiting for damage) AND not dead (game over)
                if (!isDead && (!check.isAttack || !success)) {
                    setTimeout(() => callAI(resultText, false, true, newHistory), 1000);
                }

            } catch (err) {
                console.error(err);
                setIsRolling(false);
            }
        }, 1500); 
    };

    return {
        state,
        ui: { input, isLoading, error, isRolling, rollAnimValue, showHelp, helpText },
        actions: { 
            setInput, handleAction, handleNextPhase, handleStartIntro, 
            handleHelp, handleInspect, handleRest, handleToggleEquip, 
            handleRoll, handleDamageRoll, setShowHelp 
        }
    };
};
