
import { useState, useEffect, useCallback } from 'react';

/**
 * A hook that syncs state with localStorage for a specific key.
 * Now includes auto-save functionality via useEffect.
 */
export function usePersistentState(storageKey: string, initialValue: string = '') {
  // Initialize state function to avoid reading localStorage on every render
  const [text, setText] = useState<string>(() => {
    try {
      const item = window.localStorage.getItem(storageKey);
      return item !== null ? item : initialValue;
    } catch (error) {
      console.warn(`Error reading ${storageKey} from localStorage:`, error);
      return initialValue;
    }
  });

  const [lastSaved, setLastSaved] = useState<Date | null>(null);

  // AUTO-SAVE: Automatically write to localStorage whenever 'text' changes.
  // This ensures that updates from the game engine are immediately persisted.
  useEffect(() => {
      if (text !== undefined && text !== null) {
          try {
              window.localStorage.setItem(storageKey, text);
              setLastSaved(new Date());
          } catch (error) {
              console.error(`Error saving ${storageKey} to localStorage:`, error);
          }
      }
  }, [text, storageKey]);

  // Function to manually save (kept for compatibility, though useEffect handles most cases)
  const save = useCallback(() => {
    try {
      window.localStorage.setItem(storageKey, text);
      setLastSaved(new Date());
      return true;
    } catch (error) {
      console.error(`Error saving ${storageKey} to localStorage:`, error);
      return false;
    }
  }, [text, storageKey]);

  return { text, setText, save, lastSaved };
}
