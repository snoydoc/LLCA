// hooks/useSettings.ts — Logique métier Settings : IPC browse + detect Python + restart (TIMEOUT-RESTART-01)
// Responsabilité unique : isoler les appels IPC lcca.browseDirectory, lcca.detectPython, lcca.restartServer
// de la logique de rendu du composant SettingsModal.

import { useState, useCallback } from 'react';
import { useSettingsStore } from '../stores/settingsStore';

export interface UseSettingsReturn {
  /** true pendant la détection Python auto */
  detecting: boolean;
  /** true pendant le restart du serveur MCP */
  restarting: boolean;
  /** Ouvre le sélecteur de dossier natif et met à jour workspacePath */
  handleBrowseWorkspace: () => Promise<void>;
  /** Lance la détection automatique de Python et met à jour pythonPath */
  handleDetectPython: () => Promise<void>;
  /** Redémarre le processus Python MCP (IPC server:restart) */
  handleRestartServer: () => Promise<void>;
}

export function useSettings(): UseSettingsReturn {
  const settings   = useSettingsStore();
  const [detecting, setDetecting] = useState(false);

  const handleBrowseWorkspace = useCallback(async () => {
    try {
      const path = await (window as any).lcca.browseDirectory?.();
      if (path) settings.setWorkspacePath(path);
    } catch (err) {
      console.error('[useSettings] browseDirectory:', err);
    }
  }, [settings]);

  const handleDetectPython = useCallback(async () => {
    setDetecting(true);
    try {
      const path = await (window as any).lcca.detectPython?.();
      settings.setPythonPath(path ?? '');
    } catch (err) {
      console.error('[useSettings] detectPython:', err);
    } finally {
      setDetecting(false);
    }
  }, [settings]);

  const [restarting, setRestarting] = useState(false);

  const handleRestartServer = useCallback(async () => {
    setRestarting(true);
    try {
      await (window as any).lcca.restartServer?.();
    } catch (err) {
      console.error('[useSettings] restartServer:', err);
    } finally {
      setRestarting(false);
    }
  }, []);

  return { detecting, restarting, handleBrowseWorkspace, handleDetectPython, handleRestartServer };
}
