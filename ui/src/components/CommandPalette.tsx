// CommandPalette.tsx — UI-DS-07 : groupes (cpal-grp) + raccourcis formatés (kbd)
import { useChatStore }    from '../stores/chatStore';
import { useContextStore } from '../stores/contextStore';
import { useSettingsStore } from '../stores/settingsStore';
import { useFuzzySearch }  from '../hooks/useFuzzySearch';

interface Action {
  id:        string;
  group:     string;   // catégorie pour le rendu groupé
  icon:      string;
  label:     string;
  shortcut?: string;
  handler:   () => void;
}

interface Handlers {
  newSession:     () => void;
  clearChat:      () => void;
  toggleContext:  () => void;
  focusMode:      () => void;
  restartServer:  () => void;
  openSettings:   () => void;
  toggleTheme:    () => void;
  loadSession:    (id: string) => void;
  openSpec:       (id: string) => void;
}

function buildActions(handlers: Handlers, sessions: any[], specs: any[]): Action[] {
  return [
    // ── Groupe : Actions
    { id: 'new-session',    group: 'Actions', icon: '💬', label: 'Nouvelle session',          shortcut: 'Ctrl+N',   handler: handlers.newSession },
    { id: 'clear-chat',     group: 'Actions', icon: '🗑', label: 'Effacer le chat',           shortcut: 'Ctrl+L',   handler: handlers.clearChat },
    { id: 'toggle-context', group: 'Actions', icon: '▣',  label: 'Afficher/masquer contexte', shortcut: 'Ctrl+\\',  handler: handlers.toggleContext },
    { id: 'focus-mode',     group: 'Actions', icon: '⛶',  label: 'Mode focus',                shortcut: 'Ctrl+⇧F', handler: handlers.focusMode },
    { id: 'restart-server', group: 'Actions', icon: '⟳',  label: 'Relancer McpServer',                              handler: handlers.restartServer },
    { id: 'settings',       group: 'Actions', icon: '⚙',  label: 'Paramètres',                shortcut: 'Ctrl+,',  handler: handlers.openSettings },
    { id: 'toggle-theme',   group: 'Actions', icon: '🌙', label: 'Basculer le thème',         shortcut: 'Ctrl+⇧T', handler: handlers.toggleTheme },
    // ── Groupe : Sessions
    ...sessions.slice(0, 5).map((s: any, i: number) => ({
      id:      `session-${s.id}`,
      group:   'Sessions',
      icon:    '💬',
      label:   s.title || `Session ${i + 1}`,
      handler: () => handlers.loadSession(s.id),
    })),
    // ── Groupe : Specs
    ...specs.slice(0, 5).map((sp: any) => ({
      id:      `spec-${sp.specId}`,
      group:   'Specs',
      icon:    '📋',
      label:   sp.title,
      handler: () => handlers.openSpec(sp.specId),
    })),
  ];
}

// ─── Rendu groupé ─────────────────────────────────────────────────────────────
// Répartit les actions filtrées par groupe et insère un label .cpal-grp entre chaque
function renderGrouped(
  actions:       Action[],
  selectedIndex: number,
  onSelect:      (a: Action) => void,
  onHover:       (i: number) => void,
  counter:       { current: number },
) {
  const groups: Record<string, Action[]> = {};
  for (const a of actions) {
    if (!groups[a.group]) groups[a.group] = [];
    groups[a.group].push(a);
  }

  const nodes: React.ReactNode[] = [];
  for (const [groupName, items] of Object.entries(groups)) {
    nodes.push(
      <li key={`grp-${groupName}`} className="cpal-grp" role="presentation">
        {groupName}
      </li>
    );
    for (const action of items) {
      const idx = counter.current++;
      nodes.push(
        <li
          key={action.id}
          role="option"
          aria-selected={idx === selectedIndex}
          className={`command-palette-item${idx === selectedIndex ? ' selected' : ''}`}
          onClick={() => onSelect(action)}
          onMouseEnter={() => onHover(idx)}
        >
          <span className="cp-icon" aria-hidden="true">{action.icon}</span>
          <span className="cp-label">{action.label}</span>
          {action.shortcut && (
            <kbd className="cp-shortcut" aria-label={`Raccourci ${action.shortcut}`}>
              {action.shortcut}
            </kbd>
          )}
        </li>
      );
    }
  }
  return nodes;
}

interface CommandPaletteProps {
  onClose:         () => void;
  onOpenSpec?:     (id: string) => void;
  onOpenSettings?: () => void;
}

export function CommandPalette({ onClose, onOpenSpec, onOpenSettings }: CommandPaletteProps) {
  const { sessions, createSession, setActiveSession, clearMessages } = useChatStore();
  const { activeSpecs }                                              = useContextStore();
  const { setTheme, theme, setPanelMode, panelMode }                 = useSettingsStore();

  const handlers: Handlers = {
    newSession:    () => { createSession(); onClose(); },
    clearChat:     () => { clearMessages(); onClose(); },
    toggleContext: () => { setPanelMode(panelMode === 'standard' ? 'compact' : 'standard'); onClose(); },
    focusMode:     () => { setPanelMode(panelMode === 'focus' ? 'standard' : 'focus'); onClose(); },
    restartServer: async () => {
      try { await (window as any).lcca?.restartServer?.(); } catch { /* ignore */ }
      onClose();
    },
    openSettings: () => { onOpenSettings?.(); onClose(); },
    toggleTheme:  () => { setTheme(theme === 'dark' ? 'light' : 'dark'); onClose(); },
    loadSession:  (id) => { setActiveSession(id); onClose(); },
    openSpec:     (id) => { onOpenSpec?.(id); onClose(); },
  };

  const allActions = buildActions(handlers, sessions, activeSpecs);

  const {
    query, setQuery,
    selectedIndex, setSelectedIndex,
    filtered,
    inputRef,
    handleKey,
  } = useFuzzySearch(allActions, onClose);

  return (
    <div
      className="command-palette-overlay"
      onClick={e => e.target === e.currentTarget && onClose()}
      aria-modal="true"
    >
      <div
        className="command-palette"
        role="dialog"
        aria-label="Palette de commandes"
        onKeyDown={handleKey}
      >
        {/* Ligne de recherche avec icône + pill ESC */}
        <div className="cpal-search-row">
          <span className="cpal-search-icon" aria-hidden="true">⌕</span>
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Rechercher une action…"
            className="command-palette-input"
            aria-label="Rechercher une action"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="cpal-esc-pill" aria-label="Fermer">ESC</kbd>
        </div>

        {/* Liste groupée */}
        <ul className="command-palette-list" role="listbox" aria-label="Actions disponibles">
          {filtered.length === 0 ? (
            <li className="command-palette-empty" role="option" aria-selected="false">
              Aucune action trouvée pour « {query} »
            </li>
          ) : (
            renderGrouped(
              filtered,
              selectedIndex,
              (a) => a.handler(),
              setSelectedIndex,
              { current: 0 },
            )
          )}
        </ul>
      </div>
    </div>
  );
}
