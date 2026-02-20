
import React, { useRef, useEffect, useState } from 'react';
import { CharacterSheet } from './CharacterSheet';
import { safeRender } from '../utils';
import { INITIAL_GAME_STATE, DUMMY_CHAR } from '../constants';
import { useGameEngine } from '../hooks/useGameEngine';
import { Send, AlertTriangle, ArrowRight, Loader2, Sparkles, HelpCircle, User, ShieldAlert, CheckCircle2, XCircle, Globe, ChevronUp, ScanEye, Tent, Flame, HeartCrack, Sword, Play, Dices, X, Skull } from 'lucide-react';
import { WorldGenerator } from './phases/WorldGenerator';
import { CharacterCreator } from './phases/CharacterCreator';

interface Props {
    storageKey: string;
    title: string;
    prompts: {
        worldGen: string;
        charGen: string;
        gameplay: string;
    };
}

export const GameSession: React.FC<Props> = ({ storageKey, title, prompts }) => {
    // Inject Engine
    const { state, ui, actions } = useGameEngine(storageKey, prompts);
    const [showRestMenu, setShowRestMenu] = useState(false);
    
    // Mobile Character Sheet Toggle
    const [showMobileSheet, setShowMobileSheet] = useState(false);

    // Auto-scroll
    const chatEndRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [state.history, state.phase, state.pendingCheck]);

    const handleRestClick = (type: 'short' | 'long') => {
        setShowRestMenu(false);
        actions.handleRest(type);
    };

    // --- PHASE ROUTING ---
    
    if (state.phase === 'world-creation') {
        return (
            <WorldGenerator 
                input={ui.input}
                isLoading={ui.isLoading}
                onInputChange={actions.setInput}
                onNext={actions.handleNextPhase}
            />
        );
    }

    if (state.phase === 'character-creation') {
        return (
            <CharacterCreator 
                input={ui.input}
                isLoading={ui.isLoading}
                world={state.world}
                onInputChange={actions.setInput}
                onNext={actions.handleNextPhase}
            />
        );
    }

    // --- GAMEPLAY PHASE (CHAT) ---

    return (
        <div className="flex h-full overflow-hidden bg-slate-950 relative">
            
            {/* MAIN CHAT AREA */}
            <div className="flex-1 flex flex-col h-full relative z-10 min-w-0">
                
                {/* Mobile Header for Character Sheet Toggle */}
                <div className="md:hidden h-12 border-b border-slate-800 bg-slate-950 flex items-center justify-between px-4 shrink-0">
                    <span className="text-xs font-bold text-slate-400 uppercase tracking-widest truncate">
                        {state.world?.name || "Adventure"}
                    </span>
                    <button 
                        onClick={() => setShowMobileSheet(true)}
                        className="text-cyan-500 flex items-center gap-2 text-xs font-bold uppercase border border-cyan-900/50 bg-cyan-950/20 px-3 py-1.5 rounded-full"
                    >
                        <User size={14} /> Персонаж
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 custom-scrollbar flex flex-col">
                    {state.history.filter(h => h.role !== 'system').map((entry, historyIndex) => {
                        if (entry.role === 'system') {
                             return (
                                <div key={entry.id} className="flex justify-center my-2 animate-in fade-in zoom-in duration-300">
                                    <div className="bg-rose-950/80 border border-rose-600 text-rose-200 px-6 py-2 rounded-full font-bold uppercase tracking-widest text-xs flex items-center gap-2 shadow-xl shadow-rose-900/20 text-center">
                                        <HeartCrack size={16} className="text-rose-500 shrink-0"/> {entry.text}
                                    </div>
                                </div>
                             );
                        }

                        if (entry.role === 'roll_result') {
                            const success = entry.meta.success;
                            const isAttack = entry.meta.isAttack;
                            const rolls = entry.meta.rolls || [entry.meta.roll];
                            const rollType = entry.meta.rollType || 'normal';
                            
                            let labelText = "УСПЕХ";
                            if (success) labelText = isAttack ? "ПОПАДАНИЕ" : "ПРОЙДЕНО";
                            else labelText = isAttack ? "ПРОМАХ" : "НЕУДАЧА";

                            // Helper for display text
                            const typeDisplay = rollType === 'adv' ? 'Преимущество' : rollType === 'dis' ? 'Помеха' : 'Обычный';

                            return (
                                <div key={entry.id} className="flex justify-center my-4 animate-in zoom-in-50 duration-300">
                                    <div className={`
                                        flex flex-col items-center px-4 md:px-8 py-4 rounded-xl border-2 shadow-2xl backdrop-blur-md min-w-[280px] md:min-w-[300px]
                                        ${success 
                                            ? 'bg-emerald-950/80 border-emerald-500 text-emerald-400' 
                                            : 'bg-rose-950/80 border-rose-500 text-rose-400'}
                                    `}>
                                        <div className="text-xs font-bold uppercase tracking-widest opacity-80 mb-2 border-b border-white/20 pb-1 w-full text-center">
                                            {entry.meta.reason || "Проверка навыка"}
                                        </div>
                                        
                                        <div className="flex flex-col items-center gap-2 mt-2">
                                            <div className="flex gap-4 items-center">
                                                {rolls.map((r: number, idx: number) => {
                                                    let opacity = "opacity-100";
                                                    let scale = "scale-100";
                                                    
                                                    // Only apply dimming if we have multiple dice (Adv/Dis)
                                                    if (rolls.length > 1) {
                                                        if (rollType === 'adv') {
                                                            // For advantage, highlight MAX
                                                            if (r !== Math.max(...rolls)) { opacity = "opacity-40"; scale = "scale-90"; }
                                                        } else if (rollType === 'dis') {
                                                            // For disadvantage, highlight MIN
                                                            if (r !== Math.min(...rolls)) { opacity = "opacity-40"; scale = "scale-90"; }
                                                        }
                                                    }
                                                    
                                                    return (
                                                        <div key={idx} className={`text-4xl md:text-5xl font-black font-mono tracking-tighter transition-all ${opacity} ${scale}`}>
                                                            {r}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                            
                                            <div className="text-[10px] font-bold uppercase opacity-60 bg-black/20 px-2 py-0.5 rounded">
                                                {typeDisplay}
                                            </div>
                                        </div>

                                        <div className="flex flex-col text-sm mt-3 w-full text-center border-t border-white/10 pt-2">
                                            <div className="font-bold uppercase opacity-80 mb-1">
                                                {entry.meta.attr}
                                            </div>
                                            <div className="font-bold uppercase flex items-center justify-center gap-2">
                                                {success ? <CheckCircle2 size={24}/> : <XCircle size={24}/>}
                                                {labelText}
                                            </div>
                                            <div className="font-mono opacity-80 mt-1 whitespace-nowrap">
                                                DC: {entry.meta.dc}
                                            </div>
                                            <div className="font-mono text-xs opacity-60 mt-1">
                                                {entry.meta.roll} (d20) + {entry.meta.mod} (mod) = {entry.meta.total}
                                            </div>
                                            
                                            {success && entry.meta.isAttack && (
                                                <div className="mt-4 pt-2 border-t border-white/30 w-full animate-in slide-in-from-top-2">
                                                    {entry.meta.damageValue ? (
                                                        <div className="flex flex-col items-center gap-1">
                                                            <div className="text-yellow-300 font-black text-2xl font-mono flex items-center gap-2">
                                                                <Sword size={20} className="fill-yellow-300" /> {entry.meta.damageValue}
                                                            </div>
                                                            <div className="text-[10px] text-yellow-100/60 font-mono">
                                                                Damage ({entry.meta.damageDice})
                                                            </div>
                                                        </div>
                                                    ) : (
                                                        <button 
                                                            onClick={() => actions.handleDamageRoll(historyIndex, entry.meta.damageDice || '1d4')}
                                                            className="w-full bg-yellow-600 hover:bg-yellow-500 text-white font-bold uppercase text-xs py-2 px-4 rounded shadow-lg transition-all active:scale-95 flex items-center justify-center gap-2"
                                                        >
                                                            <Dices size={16} /> Нанести урон ({entry.meta.damageDice})
                                                        </button>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            );
                        }

                        return (
                            <div key={entry.id} className={`flex ${entry.role === 'user' ? 'justify-end' : 'justify-start'} animate-in fade-in slide-in-from-bottom-2 duration-300`}>
                                <div className={`
                                    max-w-[100%] md:max-w-[85%] p-4 md:p-6 rounded-2xl text-base md:text-lg leading-relaxed relative shadow-xl
                                    ${entry.role === 'user' 
                                        ? 'bg-cyan-950/40 border border-cyan-900/50 text-cyan-50 rounded-br-sm' 
                                        : 'bg-slate-900 border border-slate-800 text-slate-200 rounded-bl-sm'
                                    }
                                `}>
                                    {entry.role === 'model' && <Sparkles size={16} className="absolute -top-3 -left-3 text-purple-500 fill-purple-500 drop-shadow-[0_0_10px_rgba(168,85,247,0.5)]" />}
                                    {safeRender(entry.text)}
                                </div>
                            </div>
                        )
                    })}
                    
                    {ui.isLoading && (
                         <div className="flex justify-start">
                             <div className="bg-slate-900 border border-slate-800 p-4 md:p-6 rounded-2xl flex items-center gap-4 text-slate-400 text-base shadow-xl">
                                <Loader2 className="animate-spin text-cyan-500" size={24} />
                                <span className="animate-pulse font-medium tracking-wide text-sm md:text-base">Гейм-мастер обдумывает ход...</span>
                             </div>
                         </div>
                    )}
                    
                    {state.pendingCheck && (
                         <div className="w-full max-w-2xl mx-auto my-4 md:my-6 p-4 md:p-6 bg-slate-950/80 border border-slate-800 rounded-xl flex flex-col items-center justify-center z-10 animate-in slide-in-from-bottom-10 shadow-[0_0_30px_rgba(6,182,212,0.15)]">
                             <div className={`text-sm font-bold uppercase tracking-widest mb-4 flex items-center gap-2 ${state.pendingCheck.isAttack ? 'text-rose-400' : 'text-cyan-400'}`}>
                                {state.pendingCheck.isAttack ? <Sword size={18} /> : <ShieldAlert size={18} />}
                                {state.pendingCheck.reason || (state.pendingCheck.isAttack ? "Атака" : "Проверка навыка")}
                             </div>
                             
                             <div className="flex gap-2 md:gap-4 w-full justify-center">
                                <button 
                                   onClick={() => actions.handleRoll('dis')}
                                   disabled={ui.isRolling}
                                   className="flex-1 bg-slate-900 hover:bg-rose-950/50 border border-slate-700 hover:border-rose-500/50 text-slate-400 hover:text-rose-400 py-4 rounded-xl font-bold uppercase transition-all shadow-lg active:scale-95 flex flex-col items-center group"
                                >
                                    <span className="text-xs md:text-sm group-hover:underline decoration-rose-500 underline-offset-4">Помеха</span>
                                    <span className="text-[10px] opacity-60">2d20 (min)</span>
                                </button>

                                <button 
                                    onClick={() => actions.handleRoll('normal')}
                                    disabled={ui.isRolling}
                                    className={`
                                        flex-[1.5] md:flex-2 w-full max-w-xs py-4 md:py-6 rounded-2xl font-black uppercase tracking-[0.2em] text-xl md:text-2xl shadow-2xl transition-all
                                        ${ui.isRolling 
                                            ? 'bg-slate-800 text-slate-500 cursor-wait' 
                                            : state.pendingCheck.isAttack 
                                                ? 'bg-gradient-to-r from-rose-700 to-orange-700 hover:from-rose-600 hover:to-orange-600 text-white ring-4 ring-transparent hover:ring-rose-500/30'
                                                : 'bg-gradient-to-r from-cyan-600 to-blue-700 hover:from-cyan-500 hover:to-blue-600 text-white ring-4 ring-transparent hover:ring-cyan-500/30'
                                        }
                                        hover:scale-105 active:scale-95
                                    `}
                                >
                                    {ui.isRolling ? (
                                        <span className="font-mono text-3xl md:text-4xl text-white animate-pulse">{ui.rollAnimValue}</span>
                                    ) : (
                                        <div className="flex flex-col items-center">
                                            <span className="text-sm md:text-lg opacity-80 font-normal mb-1">
                                                {state.pendingCheck.isAttack ? "АТАКА" : "БРОСОК"}
                                            </span>
                                            <span className="text-2xl md:text-3xl">{state.pendingCheck.attribute}</span>
                                            <span className="text-[10px] md:text-xs font-mono opacity-70 mt-1 font-medium bg-black/20 px-2 py-0.5 rounded">
                                                DC: {state.pendingCheck.difficulty || 10}
                                            </span>
                                        </div>
                                    )}
                                </button>

                                <button 
                                   onClick={() => actions.handleRoll('adv')}
                                   disabled={ui.isRolling}
                                   className="flex-1 bg-slate-900 hover:bg-emerald-950/50 border border-slate-700 hover:border-emerald-500/50 text-slate-400 hover:text-emerald-400 py-4 rounded-xl font-bold uppercase transition-all shadow-lg active:scale-95 flex flex-col items-center group"
                                >
                                    <span className="text-xs md:text-sm group-hover:underline decoration-emerald-500 underline-offset-4">Преим.</span>
                                    <span className="text-[10px] opacity-60">2d20 (max)</span>
                                </button>
                             </div>
                         </div>
                    )}

                    <div ref={chatEndRef} />
                </div>

                {state.phase === 'levelup' && (
                    <div className="absolute inset-0 bg-slate-950/90 backdrop-blur-md z-50 flex flex-col items-center justify-center p-6 animate-in fade-in duration-500">
                        <div className="w-full max-w-2xl bg-slate-900 border-2 border-amber-500/50 rounded-2xl shadow-[0_0_50px_rgba(245,158,11,0.2)] p-8 text-center relative overflow-hidden">
                            <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-transparent via-amber-500 to-transparent"></div>
                            <ChevronUp className="mx-auto text-amber-500 mb-4 animate-bounce" size={48} />
                            <h2 className="text-4xl font-black text-white uppercase tracking-widest mb-2">Новый Уровень!</h2>
                            <p className="text-slate-400 mb-8">Выберите одно из доступных улучшений для вашего персонажа.</p>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {state.levelUpChoices?.map((choice, i) => (
                                    <button 
                                        key={i}
                                        onClick={() => actions.handleAction(`Выбор уровня: ${choice.name}`)}
                                        className="bg-slate-800 hover:bg-slate-700 border border-slate-600 hover:border-amber-500 p-6 rounded-xl transition-all group text-left relative overflow-hidden"
                                    >
                                        <div className="absolute inset-0 bg-amber-500/5 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                                        <div className="text-lg font-bold text-amber-400 mb-2 group-hover:text-amber-300">{choice.name}</div>
                                        <div className="text-sm text-slate-400 leading-relaxed">{choice.description}</div>
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>
                )}
                
                {state.phase === 'gameover' && (
                    <div className="absolute inset-0 bg-rose-950/90 backdrop-blur-md z-50 flex flex-col items-center justify-center p-6 animate-in fade-in duration-1000">
                         <div className="w-full max-w-lg border-4 border-rose-600 p-8 rounded-2xl bg-black shadow-[0_0_100px_rgba(225,29,72,0.5)] text-center">
                             <Skull size={80} className="mx-auto text-rose-600 mb-6 animate-pulse"/>
                             <h1 className="text-6xl font-black text-white uppercase tracking-widest mb-4">GAME OVER</h1>
                             <p className="text-rose-200 text-lg mb-8 font-mono">Ваша история завершена.</p>
                             <button onClick={() => {
                                 // Clear storage and reload
                                 localStorage.removeItem(storageKey);
                                 window.location.reload();
                             }} className="bg-rose-700 hover:bg-rose-600 text-white px-8 py-3 rounded font-bold uppercase tracking-widest transition-all hover:scale-105 shadow-xl">
                                 Начать заново
                             </button>
                         </div>
                    </div>
                )}

                {ui.showHelp && (
                     <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in">
                        <div className="bg-slate-900 border border-slate-700 max-w-lg w-full rounded-xl shadow-2xl p-6 relative">
                            <button onClick={() => actions.setShowHelp(false)} className="absolute top-4 right-4 text-slate-500 hover:text-white"><XCircle size={24}/></button>
                            <h3 className="text-xl font-bold text-cyan-400 mb-4 flex items-center gap-2"><HelpCircle size={24}/> Подсказка Мастера</h3>
                            <div className="text-slate-300 leading-relaxed text-sm whitespace-pre-wrap">{ui.helpText}</div>
                        </div>
                     </div>
                )}

                <div className="p-4 md:p-6 bg-slate-900 border-t border-slate-800 shadow-2xl relative z-30">
                    {ui.error && (
                        <div className="absolute -top-16 left-1/2 -translate-x-1/2 bg-rose-950 text-white px-6 py-3 rounded-full border border-rose-600 text-sm font-bold flex items-center gap-3 shadow-2xl z-50 animate-in fade-in slide-in-from-bottom-2 w-max max-w-[90vw] whitespace-nowrap overflow-hidden text-ellipsis">
                             <AlertTriangle size={18} /> {ui.error}
                        </div>
                    )}

                    {!state.pendingCheck && state.phase === 'gameplay' && (
                        <div className="flex flex-wrap gap-2 md:gap-3 mb-4 max-h-32 overflow-y-auto custom-scrollbar">
                             {state.currentOptions.map((opt, i) => (
                                 <button 
                                    key={i}
                                    onClick={() => actions.handleAction(opt)}
                                    disabled={ui.isLoading}
                                    className="px-3 py-2 md:px-4 md:py-3 bg-slate-800 hover:bg-cyan-950 border border-slate-700 hover:border-cyan-500 rounded-lg text-xs md:text-sm font-medium text-slate-300 hover:text-white transition-all shadow-md text-left active:scale-[0.98]"
                                 >
                                    {opt}
                                 </button>
                             ))}
                        </div>
                    )}

                    <div className="flex gap-2 md:gap-4 items-end relative">
                        {showRestMenu && (
                            <div className="absolute bottom-full mb-4 left-0 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-2 min-w-[200px] flex flex-col gap-2 z-50 animate-in slide-in-from-bottom-2 fade-in">
                                <button onClick={() => handleRestClick('short')} className="flex items-center gap-3 p-3 hover:bg-slate-800 rounded-lg text-slate-300 hover:text-amber-400 transition-colors text-left">
                                    <Flame size={18} />
                                    <div>
                                        <div className="text-sm font-bold">Короткий отдых</div>
                                        <div className="text-[10px] opacity-70">1 час. Тратит Hit Dice.</div>
                                    </div>
                                </button>
                                <button onClick={() => handleRestClick('long')} className="flex items-center gap-3 p-3 hover:bg-slate-800 rounded-lg text-slate-300 hover:text-purple-400 transition-colors text-left border-t border-slate-800">
                                    <Tent size={18} />
                                    <div>
                                        <div className="text-sm font-bold">Длинный отдых</div>
                                        <div className="text-[10px] opacity-70">8 часов. Полное восст.</div>
                                    </div>
                                </button>
                            </div>
                        )}

                        <div className="flex-1 bg-slate-950 border border-slate-800 rounded-xl focus-within:border-cyan-700 transition-all flex flex-col shadow-inner relative">
                             <textarea
                                value={ui.input}
                                onChange={(e) => actions.setInput(e.target.value)}
                                onKeyDown={(e) => {
                                    if(e.key === 'Enter' && !e.shiftKey) {
                                        e.preventDefault();
                                        if(ui.input.trim()) actions.handleAction(ui.input);
                                    }
                                }}
                                placeholder={state.phase === 'intro' ? "Генерация истории..." : "Действие..."}
                                disabled={!!state.pendingCheck || state.phase === 'levelup' || state.phase === 'gameover' || (state.phase === 'intro' && ui.isLoading)}
                                className="w-full p-3 md:p-4 bg-transparent text-slate-100 outline-none resize-none h-14 md:h-16 text-sm md:text-base placeholder:text-slate-600 disabled:opacity-50 pr-24"
                             />
                             <div className="absolute top-1/2 -translate-y-1/2 right-2 flex items-center gap-1">
                                 <button 
                                    onClick={() => setShowRestMenu(!showRestMenu)}
                                    disabled={ui.isLoading || state.phase === 'gameover'}
                                    title="Сделать привал"
                                    className={`text-slate-600 hover:text-amber-500 transition-colors p-1.5 rounded-lg hover:bg-amber-950/30 ${showRestMenu ? 'text-amber-500 bg-amber-950/30' : ''}`}
                                 >
                                     <Tent size={18} />
                                 </button>
                                 <div className="w-px h-4 bg-slate-800 mx-1"></div>
                                 <button 
                                    onClick={actions.handleInspect}
                                    disabled={ui.isLoading || state.phase === 'gameover'}
                                    title="Осмотреться (Perception)"
                                    className="text-slate-600 hover:text-cyan-400 transition-colors p-1.5 rounded-lg hover:bg-cyan-950/30"
                                 >
                                     <ScanEye size={18} />
                                 </button>
                                 <button 
                                    onClick={actions.handleHelp} 
                                    disabled={ui.isLoading || state.phase === 'gameover'}
                                    title="Спросить совет у Мастера"
                                    className="text-slate-600 hover:text-purple-400 transition-colors p-1.5 rounded-lg hover:bg-purple-950/30"
                                 >
                                     <HelpCircle size={18} />
                                 </button>
                             </div>
                        </div>
                        <button 
                            onClick={() => actions.handleAction(ui.input)}
                            disabled={!ui.input.trim() || ui.isLoading || !!state.pendingCheck || state.phase === 'levelup' || state.phase === 'gameover'}
                            className="h-14 md:h-16 w-14 md:w-20 bg-slate-800 text-cyan-500 rounded-xl flex items-center justify-center hover:bg-cyan-600 hover:text-white active:scale-95 transition-all shadow-lg border border-slate-700 hover:border-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <Send size={24} />
                        </button>
                    </div>
                </div>
            </div>

            {/* CHARACTER SHEET SIDEBAR (RESPONSIVE) */}
            <div className={`
                fixed inset-0 z-40 bg-slate-950 md:relative md:inset-auto md:bg-transparent md:z-auto md:w-auto
                transition-transform duration-300 ease-in-out md:transform-none md:flex
                ${showMobileSheet ? 'translate-x-0' : 'translate-x-full md:translate-x-0'}
            `}>
                {/* Mobile Close Button */}
                <button 
                    onClick={() => setShowMobileSheet(false)} 
                    className="md:hidden absolute top-4 right-4 text-slate-500 hover:text-white z-50 p-2 bg-slate-900 rounded-full shadow-lg"
                >
                    <X size={24} />
                </button>

                <CharacterSheet character={state.character || DUMMY_CHAR} onToggleEquip={actions.handleToggleEquip} currencyLabel={state.world?.currencyLabel}/>
            </div>
        </div>
    );
};
