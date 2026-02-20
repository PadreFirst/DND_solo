import React, { useState } from 'react';
import { Character, InventoryItem } from '../types';
import { Shield, Heart, Zap, Box, Coins, AlertTriangle, User, Sword, Crosshair, Droplet, Archive, Brain, Eye, Hand, Feather, Mic, Info, Activity, Sparkles, Flame, Skull, CheckCircle2, Bookmark, HeartCrack } from 'lucide-react';
import { getModifier, getProficiencyBonus, lenientParse } from '../utils';

interface CharacterSheetProps {
  character: Character;
  onToggleEquip?: (itemIndex: number) => void;
  currencyLabel?: string;
}

const ALL_SKILLS = [
    { name: 'Акробатика', attr: 'dex' }, { name: 'Анализ', attr: 'int' },
    { name: 'Атлетика', attr: 'str' }, { name: 'Внимательность', attr: 'wis' },
    { name: 'Выживание', attr: 'wis' }, { name: 'Выступление', attr: 'cha' },
    { name: 'Запугивание', attr: 'cha' }, { name: 'История', attr: 'int' },
    { name: 'Ловкость рук', attr: 'dex' }, { name: 'Магия', attr: 'int' },
    { name: 'Медицина', attr: 'wis' }, { name: 'Обман', attr: 'cha' },
    { name: 'Природа', attr: 'int' }, { name: 'Проницательность', attr: 'wis' },
    { name: 'Религия', attr: 'int' }, { name: 'Скрытность', attr: 'dex' },
    { name: 'Убеждение', attr: 'cha' }, { name: 'Уход за животными', attr: 'wis' },
];

const safeNum = (val: any): number => {
    if (typeof val === 'number') return val;
    if (typeof val === 'object' && val !== null) {
        return Number(val.current || val.value || val.val || 0);
    }
    return 0;
};

const safeString = (val: any): string => {
    if (typeof val === 'string') return val;
    if (typeof val === 'number') return String(val);
    if (typeof val === 'object' && val !== null) {
        return val.name || val.value || val.text || JSON.stringify(val);
    }
    return '';
};

export const CharacterSheet: React.FC<CharacterSheetProps> = ({ character, onToggleEquip, currencyLabel }) => {
  const [activeTab, setActiveTab] = useState<'main' | 'features'>('main');
  
  const formatMod = (val: number) => val >= 0 ? `+${val}` : `${val}`;
  const profBonus = getProficiencyBonus(character.level || 1);

  // XP Logic
  const currentLevel = safeNum(character.level) || 1;
  const currentXP = safeNum(character.xp);
  const nextLevelXP = currentLevel === 1 ? 300 : currentLevel === 2 ? 900 : currentLevel * 1000; 
  const progressPercent = Math.min(100, Math.max(0, (currentXP / nextLevelXP) * 100));

  const attributesInfo: Record<string, { label: string, short: string, desc: string }> = {
    str: { label: "СИЛА", short: "STR", desc: "Физическая мощь, атлетика" },
    dex: { label: "ЛОВКОСТЬ", short: "DEX", desc: "Реакция, координация, стрельба" },
    con: { label: "ТЕЛО", short: "CON", desc: "Здоровье, выносливость" },
    int: { label: "ИНТЕЛЛЕКТ", short: "INT", desc: "Анализ, память, знания" },
    wis: { label: "МУДРОСТЬ", short: "WIS", desc: "Внимательность, интуиция, воля" },
    cha: { label: "ХАРИЗМА", short: "CHA", desc: "Влияние, обман, убеждение" }
  };

  const normalizeAttrKey = (k: string) => {
    const lower = k.toLowerCase();
    if (lower.startsWith('str')) return 'str';
    if (lower.startsWith('dex')) return 'dex';
    if (lower.startsWith('con')) return 'con';
    if (lower.startsWith('int')) return 'int';
    if (lower.startsWith('wis')) return 'wis';
    if (lower.startsWith('cha')) return 'cha';
    return lower;
  };

  const currentAttributes = character.attributes || { str: 10, dex: 10, con: 10, int: 10, wis: 10, cha: 10 };

  const getItemIcon = (type: InventoryItem['type']) => {
    switch(type) {
        case 'weapon': return <Sword size={14} className="text-rose-400" />;
        case 'armor': return <Shield size={14} className="text-cyan-400" />;
        case 'ammo': return <Crosshair size={14} className="text-amber-400" />;
        case 'consumable': return <Droplet size={14} className="text-emerald-400" />;
        default: return <Archive size={14} className="text-slate-400" />;
    }
  };

  // Helper for Saving Throws
  const getSaveMod = (attrKey: string) => {
      // Fix: Default to 10 if attribute missing to avoid -5 default
      const attrVal = currentAttributes[attrKey as keyof typeof currentAttributes];
      const safeAttrVal = attrVal === undefined ? 10 : safeNum(attrVal);
      const mod = getModifier(safeAttrVal);
      const isProficient = character.savingThrows?.some(s => s.toLowerCase() === attrKey);
      return mod + (isProficient ? profBonus : 0);
  };
  
  // Helper to render mechanics JSON nicely
  const renderMechanics = (mech: any) => {
      if (!mech) return null;

      let parsed = mech;
      // Handle if string
      if (typeof mech === 'string') {
          parsed = lenientParse(mech);
          // If parse fails and it's a simple string, render as is
          if (!parsed && mech.trim().startsWith('{')) {
               // failed to parse json
          } else if (!parsed) {
              return <div className="text-[10px] text-cyan-500 font-mono mt-1 bg-cyan-950/20 inline-block px-1 rounded">{mech}</div>;
          }
      }

      // If object (either originally or parsed)
      if (parsed && typeof parsed === 'object') {
          return (
              <div className="flex flex-wrap gap-1 mt-1">
                  {Object.entries(parsed).map(([k, v], idx) => (
                      <span key={idx} className="text-[9px] bg-slate-950 px-1 py-0.5 rounded border border-slate-800 text-slate-400 flex items-center gap-1">
                          <span className="uppercase font-bold opacity-70">{k}:</span>
                          <span className="text-cyan-400">{safeString(v)}</span>
                      </span>
                  ))}
              </div>
          );
      }
      
      // Fallback
      return <div className="text-[10px] text-cyan-500 font-mono mt-1 bg-cyan-950/20 inline-block px-1 rounded">{safeString(mech)}</div>;
  };

  const hasMagic = character.spellSlots && Object.keys(character.spellSlots).length > 0;
  
  // Death Saves Logic
  const deathSaves = character.deathSaves || { successes: 0, failures: 0 };
  const showDeathSaves = safeNum(character.hp) <= 0 || deathSaves.successes > 0 || deathSaves.failures > 0;

  return (
    <div className="w-80 md:w-96 bg-slate-950/95 backdrop-blur-xl border-l border-slate-800 h-full flex flex-col shadow-2xl z-20 font-sans shrink-0">
      
      {/* Header */}
      <div className="p-5 border-b border-slate-800 bg-slate-900/50">
        <h2 className="text-lg font-black text-white uppercase tracking-widest leading-none mb-2 break-words">{safeString(character.name) || "Создание..."}</h2>
        <div className="text-xs text-cyan-400 font-mono flex flex-wrap gap-2 font-bold uppercase items-center mb-3">
            <span className="bg-cyan-950/50 px-2 py-0.5 rounded border border-cyan-900">LVL {currentLevel}</span>
            <span className="text-slate-500">|</span>
            <span>{safeString(character.race)}</span>
            <span className="text-slate-500">|</span>
            <span>{safeString(character.class)}</span>
        </div>

        {/* XP Bar */}
        <div className="relative h-2 w-full bg-slate-800 rounded-full overflow-hidden">
            <div 
                className="absolute top-0 left-0 h-full bg-gradient-to-r from-purple-600 to-cyan-500 transition-all duration-1000"
                style={{ width: `${progressPercent}%` }}
            ></div>
        </div>
        <div className="flex justify-between mt-1 text-[10px] font-mono font-bold text-slate-500">
            <span>XP: {currentXP}</span>
            <span>NEXT: {nextLevelXP}</span>
        </div>
      </div>
      
      {/* Tabs */}
      <div className="flex border-b border-slate-800">
          <button 
            onClick={() => setActiveTab('main')}
            className={`flex-1 py-3 text-xs font-bold uppercase tracking-widest transition-colors ${activeTab === 'main' ? 'text-white bg-slate-800' : 'text-slate-500 hover:text-slate-300'}`}
          >
              Stats
          </button>
          <button 
            onClick={() => setActiveTab('features')}
            className={`flex-1 py-3 text-xs font-bold uppercase tracking-widest transition-colors ${activeTab === 'features' ? 'text-white bg-slate-800' : 'text-slate-500 hover:text-slate-300'}`}
          >
              Features
          </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6 custom-scrollbar">
        
        {/* Vitals (Always Visible) */}
        <div className="grid grid-cols-2 gap-3">
             <div className="bg-slate-900 p-2 rounded border border-slate-800 flex items-center justify-between px-4 group relative cursor-help">
                <div className="flex items-center gap-2 text-slate-500 font-bold text-xs uppercase">
                    <Shield size={14} /> AC
                </div>
                <span className="text-xl font-mono font-bold text-white">{safeNum(character.ac)}</span>
                <div className="absolute opacity-0 group-hover:opacity-100 bottom-full left-1/2 -translate-x-1/2 mb-2 bg-slate-800 text-xs p-2 rounded border border-slate-700 pointer-events-none z-50">
                    Armor Class (Защита). Чем выше, тем сложнее по вам попасть.
                </div>
            </div>
             <div className="bg-slate-900 p-2 rounded border border-slate-800 flex items-center justify-between px-4 group relative cursor-help">
                 <div className="flex items-center gap-2 text-rose-500 font-bold text-xs uppercase">
                    <Heart size={14} /> HP
                 </div>
                 <div className="text-right">
                    <span className="text-xl font-mono font-bold text-white">{safeNum(character.hp)}</span>
                    <span className="text-[10px] text-slate-500 block">/ {safeNum(character.maxHp)}</span>
                 </div>
                 <div className="absolute opacity-0 group-hover:opacity-100 bottom-full left-1/2 -translate-x-1/2 mb-2 bg-slate-800 text-xs p-2 rounded border border-slate-700 pointer-events-none z-50 w-40 text-center">
                    Hit Points (Здоровье). Если упадет до 0, вы начнете умирать.
                </div>
            </div>
        </div>

        {/* Death Saves (Conditional) */}
        {showDeathSaves && (
            <div className="bg-slate-950 border border-rose-900/50 p-3 rounded-lg flex flex-col items-center gap-2 shadow-[0_0_15px_rgba(225,29,72,0.1)]">
                <div className="text-[10px] font-bold text-rose-500 uppercase flex items-center gap-1">
                    <HeartCrack size={12}/> SPAS BROSKI OT SMERTI
                </div>
                <div className="flex w-full justify-between px-4">
                     <div className="flex gap-1 items-center">
                         <span className="text-[10px] text-emerald-500 font-bold mr-1">SUCC</span>
                         {[1,2,3].map(i => (
                             <div key={i} className={`w-3 h-3 rounded-full border border-emerald-900 ${i <= deathSaves.successes ? 'bg-emerald-500' : 'bg-slate-900'}`}></div>
                         ))}
                     </div>
                     <div className="flex gap-1 items-center">
                         <span className="text-[10px] text-rose-500 font-bold mr-1">FAIL</span>
                         {[1,2,3].map(i => (
                             <div key={i} className={`w-3 h-3 rounded-full border border-rose-900 ${i <= deathSaves.failures ? 'bg-rose-600' : 'bg-slate-900'}`}></div>
                         ))}
                     </div>
                </div>
            </div>
        )}

        {/* MAIN TAB CONTENT */}
        {activeTab === 'main' && (
            <>
                {/* Hit Dice & Spell Slots */}
                <div className="grid grid-cols-2 gap-3">
                    <div className="bg-slate-900/50 p-2 rounded border border-slate-800 flex flex-col gap-1 group relative cursor-help">
                        <div className="text-[10px] font-bold text-slate-500 uppercase flex items-center gap-1"><Flame size={12}/> Hit Dice</div>
                        <div className="font-mono text-sm text-amber-500">
                            {character.hitDice ? `${character.hitDice.current}/${character.hitDice.max} (${character.hitDice.face})` : "1d8"}
                        </div>
                    </div>
                    
                    {hasMagic && (
                    <div className="bg-slate-900/50 p-2 rounded border border-slate-800 flex flex-col gap-1 group relative cursor-help">
                        <div className="text-[10px] font-bold text-slate-500 uppercase flex items-center gap-1"><Sparkles size={12}/> Slots</div>
                        <div className="flex flex-wrap gap-1">
                            {character.spellSlots ? Object.entries(character.spellSlots).map(([lvl, slot]: [string, any]) => (
                                <div key={lvl} className="text-[10px] bg-purple-900/30 px-1 rounded border border-purple-800 text-purple-300" title={`Level ${lvl}`}>
                                L{lvl}: {slot.current}/{slot.max}
                                </div>
                            )) : null}
                        </div>
                    </div>
                    )}
                </div>

                {/* Characteristics & Saves */}
                <div>
                <div className="flex items-center gap-2 mb-3 pb-1 border-b border-slate-800">
                        <Activity size={14} className="text-rose-500"/>
                        <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Атрибуты & Спасброски</span>
                </div>
                <div className="grid grid-cols-3 gap-2">
                    {Object.entries(currentAttributes).map(([key, val]) => {
                        const normalizedKey = normalizeAttrKey(key);
                        const info = attributesInfo[normalizedKey];
                        if (!info) return null; 

                        const safeVal = val === undefined ? 10 : safeNum(val);
                        const mod = getModifier(safeVal);
                        const saveMod = getSaveMod(normalizedKey);
                        const isSaveProf = character.savingThrows?.includes(normalizedKey);

                        return (
                            <div key={key} className="group relative bg-slate-900 border border-slate-800 p-2 rounded flex flex-col items-center hover:border-cyan-500/50 transition-colors cursor-help">
                                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">{info.short}</span>
                                <span className="text-xl font-black text-white leading-none">{safeVal}</span>
                                <div className="flex items-center gap-2 mt-1 w-full justify-center">
                                    <span className={`text-xs font-mono font-bold ${mod >= 0 ? 'text-cyan-400' : 'text-rose-400'}`}>
                                        {formatMod(mod)}
                                    </span>
                                    <span className={`text-[10px] font-mono px-1 rounded ${isSaveProf ? 'bg-amber-950 text-amber-500 border border-amber-800' : 'text-slate-600 bg-slate-950'}`} title="Спасбросок">
                                        {isSaveProf ? <Shield size={8} className="inline mr-0.5"/> : null}{formatMod(saveMod)}
                                    </span>
                                </div>
                                
                                <div className="absolute opacity-0 group-hover:opacity-100 transition-opacity bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 bg-slate-800 text-slate-200 text-[10px] p-2 rounded shadow-xl border border-slate-700 pointer-events-none z-50 text-center">
                                    <div className="font-bold text-cyan-400 mb-1">{info.label}</div>
                                    {info.desc}
                                </div>
                            </div>
                        );
                    })}
                </div>
                </div>

                {/* Skills */}
                <div>
                    <div className="flex items-center gap-2 mb-3 pb-1 border-b border-slate-800">
                        <Brain size={14} className="text-purple-500"/>
                        <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Навыки</span>
                </div>
                <div className="grid grid-cols-2 gap-x-2 gap-y-1">
                    {ALL_SKILLS.map((skill) => {
                        const isProficient = character.skills?.some(s => s.toLowerCase().includes(skill.name.toLowerCase()));
                        
                        const attrKey = skill.attr;
                        let attrVal = 10;
                        for (const [k, v] of Object.entries(currentAttributes)) {
                            if (normalizeAttrKey(k) === attrKey) {
                                attrVal = safeNum(v);
                                break;
                            }
                        }

                        const mod = getModifier(attrVal);
                        const totalMod = mod + (isProficient ? profBonus : 0);
                        
                        return (
                            <div key={skill.name} className={`flex items-center justify-between text-[10px] py-1 px-2 rounded border ${isProficient ? 'bg-cyan-950/20 text-cyan-200 border-cyan-900/30' : 'text-slate-500 border-transparent'}`}>
                                <span>{skill.name}</span>
                                <span className={`font-mono font-bold ${isProficient ? 'text-cyan-400' : 'text-slate-600'}`}>{formatMod(totalMod)}</span>
                            </div>
                        )
                    })}
                </div>
                </div>

                {/* Inventory */}
                <div>
                    <div className="flex items-center gap-2 mb-3 pb-1 border-b border-slate-800 justify-between">
                        <div className="flex items-center gap-2">
                            <Box size={14} className="text-cyan-500"/>
                            <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Инвентарь</span>
                        </div>
                        {/* Always show Gold */}
                        <span className="text-sm text-amber-400 font-mono font-bold flex items-center gap-1 bg-amber-950/30 px-2 py-0.5 rounded border border-amber-900/50">
                            <Coins size={14}/> {safeNum(character.gold)} <span className="text-[10px] opacity-70">{currencyLabel || "G"}</span>
                        </span>
                </div>
                    <ul className="space-y-2">
                        {(!character.inventory || character.inventory.length === 0) && <li className="text-slate-600 italic text-xs text-center">Пусто</li>}
                        {character.inventory && character.inventory.map((item, i) => (
                            <li key={i} className={`p-2.5 rounded border transition-colors group relative ${item.equipped ? 'bg-emerald-950/20 border-emerald-500/50 shadow-[0_0_10px_rgba(16,185,129,0.1)]' : 'bg-slate-900/50 border-slate-800 hover:bg-slate-800'}`}>
                                <div className="flex items-start gap-3">
                                    <div className="mt-0.5 opacity-70 group-hover:opacity-100 flex flex-col items-center gap-1">
                                        {getItemIcon(item.type)}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex justify-between items-start">
                                            <span className={`text-sm font-medium transition-colors ${item.equipped ? 'text-emerald-300' : 'text-slate-300 group-hover:text-white'}`}>{safeString(item.name)}</span>
                                            <div className="flex items-center">
                                                {item.equipped && <span className="mr-2 text-[8px] font-bold uppercase bg-emerald-900 text-emerald-400 px-1.5 py-0.5 rounded border border-emerald-800">Equipped</span>}
                                                {item.quantity > 1 && <span className="text-[10px] bg-slate-950 px-1.5 rounded text-slate-500 font-mono border border-slate-800">x{safeNum(item.quantity)}</span>}
                                            </div>
                                        </div>
                                        {item.mechanics && renderMechanics(item.mechanics)}
                                        
                                        {/* Equip Button */}
                                        {(item.type === 'weapon' || item.type === 'armor') && onToggleEquip && (
                                            <button 
                                                onClick={(e) => { e.stopPropagation(); onToggleEquip(i); }}
                                                className={`mt-2 text-[10px] px-2 py-1 rounded uppercase font-bold tracking-wider transition-all w-full flex items-center justify-center gap-2
                                                    ${item.equipped 
                                                        ? 'bg-emerald-900 text-emerald-200 hover:bg-emerald-800' 
                                                        : 'bg-slate-800 text-slate-500 hover:text-slate-300 hover:bg-slate-700'
                                                    }`}
                                            >
                                                {item.equipped ? <><CheckCircle2 size={10}/> Equipped</> : "Equip"}
                                            </button>
                                        )}
                                    </div>
                                </div>
                            </li>
                        ))}
                    </ul>
                </div>
            </>
        )}

        {/* FEATURES TAB */}
        {activeTab === 'features' && (
            <div>
                 <div className="flex items-center gap-2 mb-3 pb-1 border-b border-slate-800">
                    <Bookmark size={14} className="text-emerald-500"/>
                    <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Черты и Способности</span>
                </div>
                {(!character.features || character.features.length === 0) && (
                    <div className="text-slate-500 italic text-xs text-center p-4">Нет активных способностей</div>
                )}
                <div className="space-y-3">
                    {character.features && character.features.map((feat, i) => (
                        <div key={i} className="bg-slate-900 border border-slate-800 rounded p-3">
                            <div className="text-sm font-bold text-white mb-1">{feat.name}</div>
                            <div className="text-xs text-slate-400 leading-relaxed">{feat.description}</div>
                        </div>
                    ))}
                </div>

                {character.conditions && character.conditions.length > 0 && (
                     <div className="mt-6">
                        <div className="flex items-center gap-2 mb-3 pb-1 border-b border-slate-800">
                            <Skull size={14} className="text-rose-500"/>
                            <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Состояния</span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                             {character.conditions.map((cond, i) => (
                                 <span key={i} className="bg-rose-950/50 text-rose-400 border border-rose-900 px-2 py-1 rounded text-xs font-bold">
                                     {cond}
                                 </span>
                             ))}
                        </div>
                     </div>
                )}
            </div>
        )}

      </div>
    </div>
  );
};