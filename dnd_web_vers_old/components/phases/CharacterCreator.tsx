
import React from 'react';
import { User, Globe, Sparkles, Loader2 } from 'lucide-react';
import { WorldData } from '../../types';
import { safeRender } from '../../utils';

interface CharacterCreatorProps {
    input: string;
    isLoading: boolean;
    world: WorldData | null;
    onInputChange: (val: string) => void;
    onNext: () => void;
}

export const CharacterCreator: React.FC<CharacterCreatorProps> = ({ input, isLoading, world, onInputChange, onNext }) => {
    return (
        <div className="flex flex-col items-center justify-center h-full p-4 overflow-hidden bg-slate-950 relative">
        <div className="absolute inset-0 bg-slate-900 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-slate-900 to-slate-950"></div>
        <div className="relative max-w-5xl w-full h-full md:h-auto md:max-h-[90vh] flex flex-col bg-slate-900/95 rounded-2xl border border-slate-700 shadow-2xl overflow-hidden animate-in fade-in duration-700">
                <div className="p-6 border-b border-slate-800 flex items-center justify-center shrink-0">
                    <User className="text-purple-500 mr-3" size={28} />
                    <h2 className="text-3xl font-black text-white uppercase tracking-widest">Создание Героя</h2>
                </div>
                <div className="flex-1 overflow-y-auto p-6 md:px-12 md:py-8 space-y-6 custom-scrollbar">
                    <div className="bg-gradient-to-r from-slate-900 to-slate-800 p-4 rounded-xl border border-slate-700 shadow-lg">
                    <h3 className="text-cyan-400 text-xs font-bold uppercase tracking-widest mb-2 flex items-center gap-2">
                        <Globe size={14}/> Текущий Мир: {safeRender(world?.name || 'Unknown')}
                    </h3>
                    <p className="text-slate-300 text-sm italic leading-relaxed opacity-90">
                        {safeRender(world?.description || 'Нет описания')}
                    </p>
                    </div>
                    <div className="space-y-4 mt-4">
                        <label className="text-purple-400 text-xs font-bold uppercase tracking-widest">Ваш Герой</label>
                        <textarea 
                            value={input}
                            onChange={(e) => onInputChange(e.target.value)}
                            placeholder="Опишите имя, расу, класс и характер..."
                            className="w-full h-32 p-4 bg-slate-950 border border-slate-700 rounded-xl text-white outline-none focus:border-purple-500 transition-colors resize-none placeholder:text-slate-600"
                        />
                    </div>
            </div>
            <div className="p-6 border-t border-slate-800 bg-slate-950 shrink-0">
                <button onClick={onNext} disabled={isLoading} className="w-full bg-slate-100 hover:bg-white text-slate-900 py-4 rounded-xl font-bold uppercase transition-transform active:scale-[0.99] shadow-lg flex items-center justify-center gap-3">
                    {isLoading ? <Loader2 className="animate-spin"/> : <>Начать Игру <Sparkles size={20} className="text-purple-600"/></>}
                </button>
            </div>
        </div>
    </div>
    );
};
