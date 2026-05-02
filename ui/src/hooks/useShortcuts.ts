import { useEffect } from 'react';

type ShortcutHandlers = Record<string, () => void>;

export function useShortcuts(handlers: ShortcutHandlers): void {
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      const ctrl = e.ctrlKey || e.metaKey;
      const key  = e.key.toLowerCase();

      if (ctrl && key === 'n')                  { e.preventDefault(); handlers['new-session']?.(); }
      if (ctrl && key === 'l')                  { e.preventDefault(); handlers['clear-chat']?.(); }
      if (ctrl && key === '\\')                 { e.preventDefault(); handlers['toggle-context']?.(); }
      if (ctrl && e.shiftKey && key === 'f')    { e.preventDefault(); handlers['focus-mode']?.(); }
      if (ctrl && key === 'k')                  { e.preventDefault(); handlers['command-palette']?.(); }
      if (ctrl && key === ',')                  { e.preventDefault(); handlers['settings']?.(); }
      if (ctrl && e.shiftKey && key === 't')    { e.preventDefault(); handlers['toggle-theme']?.(); }
      if (e.key === 'F1')                        { e.preventDefault(); handlers['help']?.(); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handlers]);
}
