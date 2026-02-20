import React, { useState } from 'react';
import { X, Save, RotateCcw } from 'lucide-react';
import { DEFAULT_PROMPTS } from '../constants';

interface Prompts {
  worldGen: string;
  charGen: string;
  gameplay: string;
}

interface SettingsModalProps {
  prompts: Prompts;
  onSave: (prompts: Prompts) => void;
  onClose: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({ prompts, onSave, onClose }) => {
  const [localPrompts, setLocalPrompts] = useState<Prompts>(prompts);
  const [activeTab, setActiveTab] = useState<keyof Prompts>('worldGen');

  const handleSave = () => {
    onSave(localPrompts);
    onClose();
  };

  const handleResetDefaults = () => {
    if(window.confirm("Сбросить все промпты к заводским настройкам?")) {
        setLocalPrompts(DEFAULT_PROMPTS);
    }
  };

  const tabs: {id: keyof Prompts, label: string}[] = [
    { id: 'worldGen', label: 'Генерация Мира' },
    { id: 'charGen', label: 'Генерация Персонажа' },
    { id: 'gameplay', label: 'Геймплей (GM)' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-700 w-full max-w-4xl h-[80vh] rounded-xl shadow-2xl flex flex-col overflow-hidden">
        
        {/* Header */}
        <div className="p-6 border-b border-slate-700 flex justify-between items-center bg-slate-950">
          <div>
            <h2 className="text-xl font-bold text-white uppercase tracking-widest flex items-center gap-2">
              Logic Core Settings
            </h2>
            <p className="text-xs text-slate-500 mt-1">Редактирование системных инструкций для ИИ</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X size={24} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 flex overflow-hidden">
            {/* Tabs */}
            <div className="w-64 bg-slate-900 border-r border-slate-800 p-4 space-y-2">
                {tabs.map(tab => (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={`w-full text-left px-4 py-3 rounded-lg text-xs font-bold uppercase tracking-wider transition-all
                            ${activeTab === tab.id 
                                ? 'bg-cyan-950/50 text-cyan-400 border border-cyan-900' 
                                : 'text-slate-500 hover:bg-slate-800 hover:text-slate-300'
                            }`}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Editor */}
            <div className="flex-1 p-6 bg-slate-950/50 flex flex-col">
                <label className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3 block">
                    System Prompt: {tabs.find(t => t.id === activeTab)?.label}
                </label>
                <textarea 
                    value={localPrompts[activeTab]}
                    onChange={(e) => setLocalPrompts({...localPrompts, [activeTab]: e.target.value})}
                    className="flex-1 w-full bg-slate-900 border border-slate-700 rounded-lg p-4 font-mono text-sm text-slate-300 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 outline-none resize-none leading-relaxed"
                    spellCheck={false}
                />
            </div>
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-slate-800 bg-slate-900 flex justify-between items-center">
            <button 
                onClick={handleResetDefaults}
                className="flex items-center gap-2 text-xs font-bold text-slate-500 hover:text-rose-400 uppercase tracking-wider transition-colors"
            >
                <RotateCcw size={16} /> Reset to Defaults
            </button>
            
            <button 
                onClick={handleSave}
                className="flex items-center gap-2 bg-cyan-700 hover:bg-cyan-600 text-white px-8 py-3 rounded-lg font-bold uppercase tracking-widest shadow-lg shadow-cyan-900/50 transition-all active:scale-95"
            >
                <Save size={18} /> Сохранить изменения
            </button>
        </div>
      </div>
    </div>
  );
};