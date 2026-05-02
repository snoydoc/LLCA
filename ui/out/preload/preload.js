"use strict";
const electron = require("electron");
electron.contextBridge.exposeInMainWorld("lcca", {
  // ── MCP ──────────────────────────────────────────────────────────────────
  mcpCall: (tool, args) => electron.ipcRenderer.invoke("mcp:call", tool, args),
  mcpStatus: () => electron.ipcRenderer.invoke("mcp:status"),
  // ── Lifecycle serveur ─────────────────────────────────────────────────────
  restartServer: () => electron.ipcRenderer.invoke("server:restart"),
  stopServer: () => electron.ipcRenderer.invoke("server:stop"),
  // ── Events serveur ────────────────────────────────────────────────────────
  onServerStatus: (cb) => {
    const handler = (_, s) => cb(s);
    electron.ipcRenderer.on("server:status", handler);
    return () => electron.ipcRenderer.off("server:status", handler);
  },
  // UI-07 : streaming tokens depuis Ollama
  onToken: (cb) => {
    const handler = (_, data) => cb(data.reqId, data.token);
    electron.ipcRenderer.on("lcca:token", handler);
    return () => electron.ipcRenderer.off("lcca:token", handler);
  },
  // ── Filesystem (whitelist workspace) ──────────────────────────────────────
  readWorkspaceFile: (relPath) => electron.ipcRenderer.invoke("fs:readWorkspaceFile", relPath),
  // BUGFIX écriture locale : writeWorkspaceFile exposé vers le renderer
  // Sécurisé côté main par whitelist (pas de traversal, pas de chemin absolu)
  writeWorkspaceFile: (relPath, content) => electron.ipcRenderer.invoke("fs:writeWorkspaceFile", relPath, content),
  // ── Sessions ──────────────────────────────────────────────────────────────
  saveSessions: (sessions) => electron.ipcRenderer.invoke("sessions:save", sessions),
  loadSessions: () => electron.ipcRenderer.invoke("sessions:load"),
  saveSessionMessages: (sessionId, messages) => electron.ipcRenderer.invoke("session:saveMessages", sessionId, messages),
  loadSessionMessages: (sessionId) => electron.ipcRenderer.invoke("session:loadMessages", sessionId),
  // ── Settings ──────────────────────────────────────────────────────────────
  saveSettings: (settings) => electron.ipcRenderer.invoke("settings:save", settings),
  loadSettings: () => electron.ipcRenderer.invoke("settings:load"),
  detectPython: () => electron.ipcRenderer.invoke("settings:detectPython"),
  // ── Dialog ────────────────────────────────────────────────────────────────
  browseDirectory: () => electron.ipcRenderer.invoke("dialog:browseDirectory"),
  // ── Window controls ───────────────────────────────────────────────────────
  windowControl: (action) => electron.ipcRenderer.send("window-control", action),
  // V9-06 : télémétrie tok/s
  readTps: (n) => electron.ipcRenderer.invoke("telemetry:readTps", n ?? 50),
  // V9-09 : historique pour TelemetryPanel
  readTelemetryHistory: (n) => electron.ipcRenderer.invoke("telemetry:readHistory", n ?? 100),
  // ROUTER-04 : online models
  onlineModels: {
    getConfig: () => electron.ipcRenderer.invoke("onlineModels:getConfig"),
    setEnabled: (id, enabled) => electron.ipcRenderer.invoke("onlineModels:setEnabled", id, enabled),
    setRoutingEnabled: (enabled) => electron.ipcRenderer.invoke("onlineModels:setRoutingEnabled", enabled),
    setKey: (id, key) => electron.ipcRenderer.invoke("onlineModels:setKey", id, key),
    testProvider: (id) => electron.ipcRenderer.invoke("onlineModels:testProvider", id)
  },
  // SI-06 : SelfImprove panel
  si: {
    getStatus: () => electron.ipcRenderer.invoke("si:getStatus"),
    getHistory: (limit) => electron.ipcRenderer.invoke("si:getHistory", limit ?? 5),
    runCommand: (command) => electron.ipcRenderer.invoke("si:runCommand", command)
  }
});
