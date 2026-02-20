import React, { useState, useEffect, useCallback, useRef } from 'react';
import { usePersistentState } from '../hooks/usePersistentState';
import { Save, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';

interface EditorProps {
  storageKey: string;
  title: string;
  initialContent?: string;
  onSave?: (content: string) => void;
}

export const Editor: React.FC<EditorProps> = ({ storageKey, title, initialContent = '', onSave }) => {
  // The hook now manages state specifically for the passed `storageKey`
  // initialContent is used if localStorage is empty for this key
  const { text, setText, save, lastSaved } = usePersistentState(storageKey, initialContent);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  
  // Ref to track if it's the first render to avoid auto-saving immediately on load
  const isFirstRender = useRef(true);

  const handleSave = useCallback(() => {
    setStatus('saving');
    // Save to localStorage
    const success = save();
    
    // Notify parent to update titles ("hardcode into section")
    if (success && onSave) {
      onSave(text);
    }

    // UX Feedback delay
    setTimeout(() => {
      if (success) {
        setStatus('saved');
        // Reset status after 2 seconds
        setTimeout(() => setStatus('idle'), 2000);
      }
    }, 400);
  }, [save, onSave, text]);

  // Auto-save effect
  useEffect(() => {
    // Skip the first render so we don't save just by opening the tab
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }

    // Debounce logic: wait 1.5s after user stops typing before saving
    const timer = setTimeout(() => {
      handleSave();
    }, 1500);

    return () => clearTimeout(timer);
  }, [text, handleSave]);

  return (
    <div className="flex flex-col h-full bg-stone-50">
      {/* Header/Toolbar */}
      <header className="h-16 bg-white border-b border-stone-200 flex items-center justify-between px-6 flex-shrink-0 shadow-sm z-10">
        <div className="flex items-center gap-3 overflow-hidden">
            <h2 className="text-lg font-serif font-bold text-emerald-950 tracking-wide truncate">{title}</h2>
            <div className="h-4 w-px bg-stone-300 mx-1 flex-shrink-0"></div>
            <span className="text-[10px] uppercase tracking-wider font-bold text-emerald-600 bg-emerald-50 px-2 py-1 rounded border border-emerald-100 flex-shrink-0">
              KEY: {storageKey.split('_').pop()}
            </span>
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
            {lastSaved && (
              <span className="text-xs font-medium text-stone-400 hidden sm:block font-serif italic">
                Saved: {lastSaved.toLocaleTimeString()}
              </span>
            )}
            
            <button
            onClick={handleSave}
            disabled={status === 'saved' || status === 'saving'}
            className={`
              flex items-center gap-2 px-6 py-2 rounded-sm font-bold text-xs uppercase tracking-widest transition-all duration-300 shadow-sm
              ${status === 'saved' 
                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 cursor-default' 
                : status === 'saving'
                  ? 'bg-emerald-800 text-emerald-200 border border-emerald-900 cursor-wait'
                  : 'bg-emerald-900 hover:bg-emerald-800 text-amber-400 border border-emerald-950 hover:border-emerald-700 shadow-emerald-900/20 hover:shadow-lg active:scale-95'
              }
            `}
            >
              {status === 'saved' ? (
                <>
                  <CheckCircle2 size={16} />
                  <span>Saved</span>
                </>
              ) : status === 'saving' ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Save size={16} />
                  <span>Save</span>
                </>
              )}
            </button>
        </div>
      </header>

      {/* Editor Area */}
      <div className="flex-1 p-6 overflow-hidden flex flex-col bg-stone-100/50">
        <div className="flex-1 relative group h-full">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={`Введите текст для "${title}"...`}
            className="w-full h-full p-8 resize-none bg-white border border-stone-200 rounded-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-amber-500/50 focus:border-amber-500 transition-all font-serif text-base leading-loose text-stone-800 placeholder:text-stone-300"
            spellCheck={false}
          />
          
          {/* Bottom Info Status */}
          <div className="absolute bottom-4 right-4 pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-300">
              <div className="bg-emerald-950 text-amber-500 text-[10px] uppercase tracking-widest px-4 py-2 rounded-sm shadow-xl flex items-center gap-2 border border-emerald-800">
                <AlertCircle size={12} className="text-amber-500" />
                <span>Chars: {text.length}</span>
              </div>
          </div>
        </div>
      </div>
    </div>
  );
};