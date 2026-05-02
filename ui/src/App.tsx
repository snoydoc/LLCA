import { useState, useEffect, useCallback } from 'react';
import { useSettingsStore } from './stores/settingsStore';
import { useChatStore }     from './stores/chatStore';
import { useContextStore }  from './stores/contextStore';
import { useProjectStore }  from './stores/projectStore';
import { useShortcuts }     from './hooks/useShortcuts';
import { Layout }                from './components/Layout';
import { CommandPalette }        from './components/CommandPalette';
import { SettingsModal }         from './components/SettingsModal';
import { HelpModal }             from './components/HelpModal';
import { ProjectWelcomeScreen }  from './components/ProjectWelcomeScreen';
import type { ProjectMeta }      from './stores/projectStore';

export default function App() {
  const settings = useSettingsStore();
  const { createSession, loadSessions } = useChatStore();
  const { startPolling, refreshWorkspace, refreshSpecs } = useContextStore();
  const { activeProject } = useProjectStore();

  // ── UI-04 : CommandPalette ────────────────────────────────────────────────
  const [showPalette,  setShowPalette]  = useState(false);
  // ── UI-05 : SettingsModal ─────────────────────────────────────────────────
  const [showSettings, setShowSettings] = useState(false);
  // BUGFIX MODAL-01 : HelpModal (bouton Aide n'avait pas d'onClick ni de modale)
  const [showHelp,     setShowHelp]     = useState(false);

  const openPalette   = useCallback(() => setShowPalette(true),   []);
  const closePalette  = useCallback(() => setShowPalette(false),  []);
  const openSettings  = useCallback(() => setShowSettings(true),  []);
  const closeSettings = useCallback(() => setShowSettings(false), []);
  const openHelp      = useCallback(() => setShowHelp(true),      []);
  const closeHelp     = useCallback(() => setShowHelp(false),     []);

  // ── Initialisation au démarrage ──────────────────────────────────────────
  useEffect(() => {
    settings.load().catch(console.error);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Application du thème ─────────────────────────────────────────────────
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', settings.theme);
  }, [settings.theme]);

  // ── Taille de police (3 niveaux) ─────────────────────────────────────────
  useEffect(() => {
    const map = {
      sm: { base: '12px', sm: '11px', xs: '10px' },
      md: { base: '14px', sm: '13px', xs: '11px' },
      lg: { base: '16px', sm: '15px', xs: '13px' },
    } as const;
    const sizes = map[settings.fontSize];
    const root = document.documentElement;
    root.style.setProperty('--font-size-base', sizes.base);
    root.style.setProperty('--font-size-sm',   sizes.sm);
    root.style.setProperty('--font-size-xs',   sizes.xs);
  }, [settings.fontSize]);

  // ── Chargement des sessions après settings ────────────────────────────────
  useEffect(() => {
    loadSessions().catch(() => {
      createSession();
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Démarrage du polling MCP + refresh initial ───────────────────────────
  useEffect(() => {
    const stopPolling = startPolling();
    const t = setTimeout(() => {
      refreshWorkspace().catch(() => {});
      refreshSpecs().catch(() => {});
    }, 2000);
    return () => {
      stopPolling();
      clearTimeout(t);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Communication App → ChatPanel pour open-spec depuis la palette ────────
  const handleOpenSpec = useCallback((id: string) => {
    window.dispatchEvent(new CustomEvent('lcca:open-spec', { detail: { specId: id } }));
    closePalette();
  }, [closePalette]);

  // PROJ-UI-05 : callback quand un projet est ouvert depuis ProjectWelcomeScreen
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleProjectOpen = useCallback((_project: ProjectMeta) => {
    // Le store a déjà mis activeProject à jour via openProject()
    // Rien de plus à faire : le gate ci-dessous bascule automatiquement vers Layout
  }, []);

  // ── Raccourcis globaux ────────────────────────────────────────────────────
  useShortcuts({
    'new-session':    () => createSession(),
    'clear-chat':     () => useChatStore.getState().clearMessages(),
    'toggle-theme':   () => settings.setTheme(settings.theme === 'dark' ? 'light' : 'dark'),
    'toggle-context': () =>
      settings.setPanelMode(settings.panelMode === 'standard' ? 'compact' : 'standard'),
    'focus-mode':     () =>
      settings.setPanelMode(settings.panelMode === 'focus' ? 'standard' : 'focus'),
    'command-palette': openPalette,   // Ctrl+K  — UI-04
    'settings':        openSettings,  // Ctrl+,  — UI-05
    'help':            openHelp,      // F1      — BUGFIX MODAL-01
  });

  return (
    <>
      {/* PROJ-UI-05 : gate Mode Projets
          Sans projet actif → écran d'accueil projets
          Projet actif       → interface chat normale */}
      {!activeProject ? (
        <ProjectWelcomeScreen onProjectOpen={handleProjectOpen} />
      ) : (
        /* BUGFIX MODAL-01 : callbacks propagés jusqu'à Sidebar via Layout */
        <Layout onOpenSettings={openSettings} onOpenHelp={openHelp} />
      )}

      {/* CommandPalette — UI-04 */}
      {showPalette && (
        <CommandPalette
          onClose={closePalette}
          onOpenSpec={handleOpenSpec}
          onOpenSettings={() => { openSettings(); closePalette(); }}
        />
      )}

      {/* SettingsModal — UI-05 */}
      {showSettings && (
        <SettingsModal onClose={closeSettings} />
      )}

      {/* HelpModal — BUGFIX MODAL-01 */}
      {showHelp && (
        <HelpModal onClose={closeHelp} />
      )}
    </>
  );
}
