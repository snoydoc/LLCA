import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('lcca', {
  // ── MCP ──────────────────────────────────────────────────────────────────
  mcpCall:   (tool: string, args: object) => ipcRenderer.invoke('mcp:call', tool, args),
  mcpStatus: ()                           => ipcRenderer.invoke('mcp:status'),

  // ── Lifecycle serveur ─────────────────────────────────────────────────────
  restartServer: () => ipcRenderer.invoke('server:restart'),
  stopServer:    () => ipcRenderer.invoke('server:stop'),

  // ── Events serveur ────────────────────────────────────────────────────────
  onServerStatus: (cb: (s: unknown) => void) => {
    const handler = (_: unknown, s: unknown) => cb(s);
    ipcRenderer.on('server:status', handler);
    return () => ipcRenderer.off('server:status', handler);
  },

  // UI-07 : streaming tokens depuis Ollama
  onToken: (cb: (reqId: number, token: string) => void) => {
    const handler = (_: unknown, data: { reqId: number; token: string }) =>
      cb(data.reqId, data.token);
    ipcRenderer.on('lcca:token', handler);
    return () => ipcRenderer.off('lcca:token', handler);
  },

  // ── Filesystem (whitelist workspace) ──────────────────────────────────────
  readWorkspaceFile: (relPath: string) =>
    ipcRenderer.invoke('fs:readWorkspaceFile', relPath),

  // BUGFIX écriture locale : writeWorkspaceFile exposé vers le renderer
  // Sécurisé côté main par whitelist (pas de traversal, pas de chemin absolu)
  writeWorkspaceFile: (relPath: string, content: string) =>
    ipcRenderer.invoke('fs:writeWorkspaceFile', relPath, content),

  // ── Sessions ──────────────────────────────────────────────────────────────
  saveSessions:     (sessions: unknown[]) =>
    ipcRenderer.invoke('sessions:save', sessions),
  loadSessions:     () =>
    ipcRenderer.invoke('sessions:load'),
  saveSessionMessages: (sessionId: string, messages: unknown[]) =>
    ipcRenderer.invoke('session:saveMessages', sessionId, messages),
  loadSessionMessages: (sessionId: string) =>
    ipcRenderer.invoke('session:loadMessages', sessionId),

  // ── Settings ──────────────────────────────────────────────────────────────
  saveSettings: (settings: object) =>
    ipcRenderer.invoke('settings:save', settings),
  loadSettings: () =>
    ipcRenderer.invoke('settings:load'),
  detectPython: () =>
    ipcRenderer.invoke('settings:detectPython'),

  // ── Dialog ────────────────────────────────────────────────────────────────
  browseDirectory: () =>
    ipcRenderer.invoke('dialog:browseDirectory'),

  // ── Window controls ───────────────────────────────────────────────────────
  windowControl: (action: 'minimize' | 'maximize' | 'close') =>
    ipcRenderer.send('window-control', action),

  // V9-06 : télémétrie tok/s
  readTps: (n?: number) =>
    ipcRenderer.invoke('telemetry:readTps', n ?? 50),

  // V9-09 : historique pour TelemetryPanel
  readTelemetryHistory: (n?: number) =>
    ipcRenderer.invoke('telemetry:readHistory', n ?? 100),

  // ROUTER-04 : online models
  onlineModels: {
    getConfig:         ()                                    => ipcRenderer.invoke('onlineModels:getConfig'),
    setEnabled:        (id: string, enabled: boolean)        => ipcRenderer.invoke('onlineModels:setEnabled', id, enabled),
    setRoutingEnabled: (enabled: boolean)                    => ipcRenderer.invoke('onlineModels:setRoutingEnabled', enabled),
    setKey:            (id: string, key: string)             => ipcRenderer.invoke('onlineModels:setKey', id, key),
    testProvider:      (id: string)                          => ipcRenderer.invoke('onlineModels:testProvider', id),
  },

  // SI-06 : SelfImprove panel
  si: {
    getStatus:  ()                    => ipcRenderer.invoke('si:getStatus'),
    getHistory: (limit?: number)      => ipcRenderer.invoke('si:getHistory', limit ?? 5),
    runCommand: (command: string)     => ipcRenderer.invoke('si:runCommand', command),
  },

  // PROJ-05 : Mode Projets
  projects: {
    list:    ()                                        => ipcRenderer.invoke('project:list'),
    open:    (id: string)                             => ipcRenderer.invoke('project:open', id),
    create:  (name: string, description: string, tags?: string[], storageMode?: string) => ipcRenderer.invoke('project:create', name, description, tags ?? [], storageMode ?? 'shared'),
    archive: (id: string)                             => ipcRenderer.invoke('project:archive', id),
  },

  // PROJ-UI-01 : UserContext
  userContext: {
    read:    () => ipcRenderer.invoke('userctx:read'),
    setName: (name: string) => ipcRenderer.invoke('userctx:setName', name),
  },

  // VOICE-07 : pipeline voix STT + TTS
  voice: {
    start:  () => ipcRenderer.invoke('voice:start'),
    stop:   () => ipcRenderer.invoke('voice:stop'),
    status: () => ipcRenderer.invoke('voice:status'),
  },
  tts: {
    start:  () => ipcRenderer.invoke('tts:start'),
    stop:   () => ipcRenderer.invoke('tts:stop'),
    status: () => ipcRenderer.invoke('tts:status'),
  },
});
