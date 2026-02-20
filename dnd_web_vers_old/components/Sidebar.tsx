
import React, { useEffect, useState } from 'react';
import { SIDEBAR_BUTTON_COUNT, STORAGE_KEY } from '../constants';
import { Database, Circle, Cpu, PlayCircle } from 'lucide-react';
import { GameState } from '../types';

interface SidebarProps {
  activeIndex: number;
  onButtonClick: (index: number) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ activeIndex, onButtonClick }) => {
  // Helper to peek at local storage to show status labels
  const getStatus = (index: number) => {
    try {
      const key = `${STORAGE_KEY}_campaign_${index}`;
      const data = localStorage.getItem(key);
      if (!data) return 'Свободно';
      const state: GameState = JSON.parse(data);
      if (state.phase === 'world-creation') return 'Генерация мира';
      if (state.phase === 'character-creation') return 'Создание героя';
      if (state.phase === 'intro') return 'Интро';
      return 'В игре';
    } catch {
      return 'Ошибка';
    }
  };

  return (
    <aside className="w-64 bg-slate-950 border-r border-slate-800 flex flex-col h-full z-30 shadow-2xl pt-2">
      <nav className="flex-1 overflow-y-auto p-2 space-y-1 custom-scrollbar">
        {Array.from({ length: SIDEBAR_BUTTON_COUNT }).map((_, index) => {
          const isActive = activeIndex === index;
          const status = getStatus(index);
          const isUsed = status !== 'Свободно';
          
          return (
            <button
              key={index}
              onClick={() => onButtonClick(index)}
              className={`
                w-full text-left px-3 py-3 rounded-lg transition-all duration-200 group flex items-center gap-3 border border-transparent
                ${isActive 
                  ? 'bg-slate-800 border-slate-700 shadow-lg' 
                  : 'hover:bg-slate-900'
                }
              `}
            >
              <div className={`
                flex-shrink-0 flex items-center justify-center w-8 h-8 rounded bg-slate-900 border transition-colors
                ${isActive 
                  ? 'border-cyan-500 text-cyan-400 shadow-[0_0_10px_rgba(6,182,212,0.3)]' 
                  : isUsed 
                    ? 'border-slate-700 text-slate-400 group-hover:border-slate-600'
                    : 'border-slate-800 text-slate-700'
                }
              `}>
                <span className="text-xs font-mono font-bold">{index + 1}</span>
              </div>
              
              <div className="flex flex-col min-w-0">
                <span className={`text-xs font-bold truncate ${isActive ? 'text-white' : 'text-slate-400 group-hover:text-slate-200'}`}>
                   {isUsed ? `Сессия ${index + 1}` : `Слот ${index + 1}`}
                </span>
                <span className="text-[10px] truncate uppercase tracking-wide text-slate-600 group-hover:text-slate-500">
                  {status}
                </span>
              </div>

              {isActive && isUsed && (
                <PlayCircle size={14} className="ml-auto text-cyan-500 animate-pulse" />
              )}
            </button>
          );
        })}
      </nav>

      {/* Bottom Status */}
      <div className="p-4 border-t border-slate-800 text-[10px] text-slate-600 flex justify-between uppercase tracking-wider">
        <span>System: Online</span>
        <span className="flex items-center gap-1"><Cpu size={10}/> Gemini 3.0</span>
      </div>
    </aside>
  );
};
