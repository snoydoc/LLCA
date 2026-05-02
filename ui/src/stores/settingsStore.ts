import { create } from 'zustand';

type Theme     = 'dark' | 'light';
type PanelMode = 'standard' | 'compact' | 'focus';
type FontSize  = 'sm' | 'md' | 'lg';

interface SettingsState {
  theme:           Theme;
  panelMode:       PanelMode;
  fontSize:        FontSize;
  streamingDelay:  number;    // ms/token — 0 = instantané
  autoStartServer: boolean;
  workspacePath:   string;
  pythonPath:      string;

  // Setters
  setTheme:           (t: Theme)         => void;
  setPanelMode:       (m: PanelMode)     => void;
  setFontSize:        (s: FontSize)      => void;
  setStreamingDelay:  (d: number)        => void;
  setAutoStartServer: (v: boolean)       => void;
  setWorkspacePath:   (p: string)        => void;
  setPythonPath:      (p: string)        => void;

  // Persistence
  persist: () => Promise<void>;
  load:    () => Promise<void>;
}

let _debounceTimer: ReturnType<typeof setTimeout> | null = null;
function debouncedPersist(fn: () => Promise<void>, ms = 300) {
  if (_debounceTimer) clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => fn().catch(console.error), ms);
}

export const useSettingsStore = create<SettingsState>()((set, get) => ({
  theme:           'dark',
  panelMode:       'standard',
  fontSize:        'md',
  streamingDelay:  15,
  autoStartServer: true,
  workspacePath:   'D:\\LLMCodeAgent',
  pythonPath:      '',

  setTheme:           (t) => { set({ theme: t });          debouncedPersist(() => get().persist()); },
  setPanelMode:       (m) => { set({ panelMode: m });      debouncedPersist(() => get().persist()); },
  setFontSize:        (s) => { set({ fontSize: s });       debouncedPersist(() => get().persist()); },
  setStreamingDelay:  (d) => { set({ streamingDelay: d }); debouncedPersist(() => get().persist()); },
  setAutoStartServer: (v) => { set({ autoStartServer: v}); debouncedPersist(() => get().persist()); },
  setWorkspacePath:   (p) => { set({ workspacePath: p });  debouncedPersist(() => get().persist()); },
  setPythonPath:      (p) => { set({ pythonPath: p });     debouncedPersist(() => get().persist()); },

  persist: async () => {
    const { theme, panelMode, fontSize, streamingDelay,
            autoStartServer, workspacePath, pythonPath } = get();
    await (window as any).lcca.saveSettings({
      theme, panelMode, fontSize, streamingDelay,
      autoStartServer, workspacePath, pythonPath,
    });
  },

  load: async () => {
    const saved = await (window as any).lcca.loadSettings();
    if (saved) set({ ...saved });
  },
}));
