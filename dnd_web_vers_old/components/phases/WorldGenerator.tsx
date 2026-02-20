
import React from 'react';
import { Globe, ArrowRight, Loader2 } from 'lucide-react';

interface WorldGeneratorProps {
    input: string;
    isLoading: boolean;
    onInputChange: (val: string) => void;
    onNext: () => void;
}

export const WorldGenerator: React.FC<WorldGeneratorProps> = ({ input, isLoading, onInputChange, onNext }) => {
    return (
        <div className="flex flex-col items-center justify-center h-full p-4 overflow-hidden bg-[url('https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=2072&auto=format&fit=crop')] bg-cover bg-center">
            <div className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm"></div>
            <div className="relative max-w-5xl w-full h-full md:h-auto md:max-h-[90vh] flex flex-col bg-slate-900/90 rounded-2xl border border-slate-700 shadow-2xl overflow-hidden animate-in fade-in duration-700">
                    <div className="p-6 border-b border-slate-800 flex items-center justify-center shrink-0">
                        <Globe className="text-cyan-500 mr-3" size={28} />
                        <h2 className="text-3xl font-black text-white uppercase tracking-widest">Генерация Мира</h2>
                    </div>
                    <div className="flex-1 overflow-y-auto p-6 md:px-12 md:py-8 space-y-6 custom-scrollbar">
                        <div className="bg-slate-950/50 p-6 rounded-xl border border-slate-800 text-slate-300 leading-relaxed text-sm md:text-base">
                            <p className="mb-4"><strong className="text-cyan-400">Приветствую тебя, дорогой игрок!</strong> Это AI DND. Отличий от классики 2:</p>
                            <ul className="list-disc list-inside mb-4 space-y-1 ml-2">
                                <li>Ты играешь один</li>
                                <li>Ты можешь создать абсолютно любой мир.</li>
                            </ul>
                        </div>
                        <div className="space-y-4">
                        <label className="text-cyan-400 text-xs font-bold uppercase tracking-widest">Ваше описание мира</label>
                        <textarea 
                                value={input}
                                onChange={(e) => onInputChange(e.target.value)}
                                placeholder="Опишите желаемый мир (например: Киберпанк-Москва 2099)..."
                                className="w-full h-32 p-4 bg-slate-950 border border-slate-700 rounded-xl text-white outline-none focus:border-cyan-500 transition-colors resize-none placeholder:text-slate-600"
                        />
                        </div>
                    </div>
                    <div className="p-6 border-t border-slate-800 bg-slate-950 shrink-0">
                    <button onClick={onNext} disabled={isLoading} className="w-full bg-cyan-700 hover:bg-cyan-600 text-white py-4 rounded-xl font-bold uppercase transition-transform active:scale-[0.99] shadow-lg flex items-center justify-center gap-3">
                        {isLoading ? <Loader2 className="animate-spin" /> : <>Создать Мир <ArrowRight size={20}/></>}
                    </button>
                    </div>
            </div>
        </div>
    );
};
