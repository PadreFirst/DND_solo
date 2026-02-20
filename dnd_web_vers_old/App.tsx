
import React, { useState } from 'react';
import { GameSession } from './components/GameSession';
import { SettingsModal } from './components/SettingsModal';
import { STORAGE_KEY, DEFAULT_PROMPTS } from './constants';
import { Terminal, RefreshCw, Settings } from 'lucide-react';
import { usePersistentState } from './hooks/usePersistentState';

const App: React.FC = () => {
  const [showSettings, setShowSettings] = useState(false);
  const [activeSessionIndex, setActiveSessionIndex] = useState(0);
  
  // Single session mode (Slot 0) since sidebar is removed
  const SESSION_KEY = `${STORAGE_KEY}_session_${activeSessionIndex}`;
  
  // Store prompts in localStorage so user tweaks persist
  const { text: promptsJson, setText: setPromptsJson } = usePersistentState(
    `${STORAGE_KEY}_system_prompts_v2.5`, 
    JSON.stringify(DEFAULT_PROMPTS)
  );

  const prompts = JSON.parse(promptsJson || JSON.stringify(DEFAULT_PROMPTS));

  const handleUpdatePrompts = (newPrompts: typeof DEFAULT_PROMPTS) => {
    setPromptsJson(JSON.stringify(newPrompts));
  };

  const handleReset = () => {
    if (window.confirm(`/// WARNING: SESSION PURGE ///\nЭто действие полностью удалит текущего персонажа и мир. Начать новую игру?`)) {
      localStorage.removeItem(SESSION_KEY);
      window.location.reload();
    }
  };

  return (
    <div className="h-screen w-screen bg-slate-950 text-slate-100 flex flex-col overflow-hidden font-sans selection:bg-cyan-500/30 selection:text-cyan-200">
      
      {/* Header */}
      <header className="h-14 border-b border-slate-800/50 bg-slate-950/80 backdrop-blur-md flex items-center justify-between px-6 shrink-0 z-20">
          <div className="flex items-center gap-3">
            <div className="text-cyan-500 animate-pulse">
              <Terminal size={20} />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-widest uppercase text-slate-100 flex items-center gap-2">
                AI_DND <span className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-950 border border-cyan-800 text-cyan-400">CORE v6.0</span>
              </h1>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
             <button 
              onClick={() => setShowSettings(true)}
              className="group flex items-center gap-2 px-3 py-1.5 rounded-full border border-slate-800 hover:border-cyan-500/50 bg-slate-900/50 transition-all text-slate-400 hover:text-cyan-400"
              title="Настройки логики (Промпты)"
            >
              <Settings size={14} className="group-hover:rotate-90 transition-transform duration-500" />
              <span className="text-[10px] font-bold uppercase hidden md:inline">Logic Core</span>
            </button>

             <button 
              onClick={handleReset}
              className="group flex items-center gap-2 px-3 py-1.5 rounded-full border border-slate-800 hover:border-rose-500/50 bg-slate-900/50 transition-all text-slate-400 hover:text-rose-400"
              title="Начать новую игру"
            >
              <RefreshCw size={14} className="group-hover:rotate-180 transition-transform duration-500" />
              <span className="text-[10px] font-bold uppercase hidden md:inline">New Game</span>
            </button>
          </div>
      </header>

      {/* Main Layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Main Content Area - Game Session (Full Width) */}
        <main className="flex-1 overflow-hidden relative bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-slate-950 w-full">
            <GameSession 
                key={SESSION_KEY}
                storageKey={SESSION_KEY}
                title={`Session ${activeSessionIndex + 1}`}
                prompts={prompts}
            />
        </main>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <SettingsModal 
          prompts={prompts} 
          onSave={handleUpdatePrompts} 
          onClose={() => setShowSettings(false)} 
        />
      )}

    </div>
  );
};

export default App;
