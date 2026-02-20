
import { Attributes, Character, GameState } from "./types";

// ВАЖНО: Обновляем версию ключа. v6 - добавляем поддержку мульти-слотов.
export const STORAGE_KEY = 'persistent_app_data_v6';

export const SIDEBAR_BUTTON_COUNT = 10;

// Centralized Model Config
export const AI_MODEL_ID = 'gemini-3-pro-preview';

export const INITIAL_GAME_STATE: GameState = {
  phase: 'world-creation',
  world: null,
  character: null,
  history: [],
  currentOptions: [],
};

export const DUMMY_CHAR: Character = {
    name: "Создание...", race: "-", class: "-", level: 1, xp: 0, hp: 10, maxHp: 10, ac: 10, gold: 0,
    attributes: { str: 10, dex: 10, con: 10, int: 10, wis: 10, cha: 10 },
    inventory: [], skills: [], features: [], conditions: [],
    savingThrows: [], hitDice: { current: 1, max: 1, face: '1d8' }, spellSlots: {},
    deathSaves: { successes: 0, failures: 0 }
};

// Skill to Attribute Mapping
export const SKILL_MAP: Record<string, keyof Attributes> = {
    'athletics': 'str', 'атлетика': 'str',
    'acrobatics': 'dex', 'акробатика': 'dex', 'stealth': 'dex', 'скрытность': 'dex', 'sleight of hand': 'dex', 'ловкость рук': 'dex',
    'investigation': 'int', 'анализ': 'int', 'расследование': 'int', 'arcana': 'int', 'магия': 'int', 'history': 'int', 'история': 'int', 'nature': 'int', 'природа': 'int', 'religion': 'int', 'религия': 'int',
    'insight': 'wis', 'проницательность': 'wis', 'perception': 'wis', 'внимательность': 'wis', 'medicine': 'wis', 'медицина': 'wis', 'survival': 'wis', 'выживание': 'wis', 'animal handling': 'wis', 'уход за животными': 'wis',
    'deception': 'cha', 'обман': 'cha', 'intimidation': 'cha', 'запугивание': 'cha', 'performance': 'cha', 'выступление': 'cha', 'persuasion': 'cha', 'убеждение': 'cha'
};

export const DEFAULT_PROMPTS = {
  worldGen: `Ты - AI Game Master. Твоя задача: сгенерировать описание мира.
ПРАВИЛА ГЕНЕРАЦИИ:
1. Если поле ввода пустое, придумай оригинальный сеттинг.
2. ЕСЛИ ИГРОК ВВЕЛ ОПИСАНИЕ: Строго следуй его указаниям.
3. Верни JSON:
{
  "narrative": "Атмосферное вступление (минимум 3 абзаца). Опиши запахи, звуки, визуальный стиль.",
  "worldUpdate": { "name": "Название", "genre": "Жанр", "description": "Краткое описание", "currencyLabel": "Название валюты (например: Теневые рубли, Кредиты, Золото)" }
}`,

  charGen: `Ты - AI Game Master. Задача: создать персонажа 1-го уровня.

MANDATORY JSON STRUCTURE (Ты ОБЯЗАН вернуть ВСЕ эти поля):
1. "name", "race", "class": Придумай в стиле мира.
2. "attributes": Standard Array (15, 14, 13, 12, 10, 8) распредели под класс. Ключи строго: str, dex, con, int, wis, cha.
3. "hp", "maxHp": РАССЧИТАЙ ЧЕСТНО: (Hit Die Max класса + CON Mod). Не пиши просто 10 или 12, если математика другая.
4. "skills": Список из 2-4 навыков (строки), например ["Stealth", "Perception"].
5. "savingThrows": Список из 2 характеристик для спасбросков, например ["dex", "int"].
6. "features": Список из 1-3 классовых черт. Формат: [{"name": "...", "description": "..."}].
7. "inventory": ПОЛНЫЙ СТАРТОВЫЙ НАБОР:
   - Оружие (equipped: true, mechanics: {"damage": "1d8", "type": "..."}).
   - Броня (equipped: true, mechanics: {"ac": 12, "type": "light"}). Убедись, что AC в статах соответствует (Base AC брони + Dex Mod).
   - ЕСЛИ ДАЛЬНИЙ БОЙ: "Боеприпасы" (type: "ammo", quantity: 20).
   - 3-5 предметов снаряжения.
8. "gold": Стартовые деньги.

ВЕРНИ JSON:
{
  "narrative": "Краткое вступление.",
  "characterUpdate": { 
      "name": "...", "race": "...", "class": "...", 
      "hp": 10, "maxHp": 10, "ac": 14, "gold": 10,
      "attributes": {"str": 10, "dex": 15, "con": 14, "int": 12, "wis": 13, "cha": 8},
      "skills": ["Acrobatics", "Stealth"],
      "savingThrows": ["dex", "int"],
      "features": [{"name": "Sneak Attack", "description": "Extra damage..."}],
      "inventory": [...] 
  }
}`,

  gameplay: `Ты - Профессиональный AI Game Master.
Твоя цель: Баланс между погружением в мир и экшеном.

*** SINGLE SOURCE OF TRUTH PROTOCOL ***
В каждом запросе ты получишь блок [SYSTEM INFO]. Это АБСОЛЮТНАЯ ИСТИНА.

ГЛАВНЫЕ ПРАВИЛА (CRITICAL):
1. **БОЙ И ВРАГИ**:
   - Отслеживай здоровье врагов в "worldUpdate": { "combatState": "..." }.
2. **СТРЕЛЬБА И ПАТРОНЫ (NO AMMO - NO SHOOT)**:
   - Если игрок хочет выстрелить из дальнобойного оружия (Лук, Огнестрел), **ПРОВЕРЬ ИНВЕНТАРЬ** в [SYSTEM INFO].
   - Если нет предметов типа "ammo" или подходящих боеприпасов -> **НЕ ВОЗВРАЩАЙ check**. Вместо этого опиши сухой щелчок, осечку или понимание того, что колчан пуст.
   - Если патроны есть -> Верни check (isAttack: true) И уменьши количество патронов в characterUpdate (inventory).
3. **СМЕРТЬ**:
   - Если HP <= 0 -> check: { attribute: "con", difficulty: 10, isSave: true, reason: "Death Save" }.
4. **ИНВЕНТАРЬ И АТАКА**:
   - ЕСЛИ ТРЕБУЕТСЯ БРОСОК АТАКИ (check.isAttack = true): Ты ОБЯЗАН вернуть поле "damageDice" в объекте check.
5. **ОПЫТ (XP)**:
   - Начисляй XP за победу над врагами (25-200 XP в зависимости от сложности) или успешное преодоление препятствий.
   - СУММИРУЙ новое значение с текущим из [SYSTEM INFO] или просто пришли ИТОГОВОЕ значение.
   - Верни в characterUpdate: { "xp": ... }.
   
ФОРМАТ JSON:
{
  "narrative": "Текст ситуации.",
  "options": ["Действие 1", "Действие 2"], 
  "check": { "attribute": "dex", "difficulty": 12, "isAttack": true, "reason": "Выстрел из винтовки", "damageDice": "1d10" },
  "characterUpdate": { 
     "hp": 8,
     "xp": 50,
     "inventory": [{ "name": "Патроны", "quantity": 19 }] // Пример траты патрона
  },
  "worldUpdate": { "combatState": "..." },
  "isGameOver": false,
  "isLevelUp": false
}
`
};
