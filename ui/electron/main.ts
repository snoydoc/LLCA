import { app, BrowserWindow, ipcMain, dialog } from 'electron';
import { join } from 'path';
import { existsSync, mkdirSync, writeFileSync, readFileSync } from 'fs';
import { spawn } from 'child_process';
import { McpBridge } from './mcp-bridge';
// @ts-ignore — electron-store ESM compat
import Store from 'electron-store';

let win: BrowserWindow | null = null;
let bridge: McpBridge | null = null;
const store = new Store();

// ─── Workspace path ───────────────────────────────────────────────────────────
function getWorkspacePath(): string {
  return (store.get('settings') as Record<string, unknown>)?.workspacePath as string
    ?? 'D:\\LLMCodeAgent';
}

// ─── Sessions persistence ─────────────────────────────────────────────────────
function getSessionsDir(): string {
  const dir = join(app.getPath('userData'), 'sessions');
  mkdirSync(dir, { recursive: true });
  return dir;
}

// ─── Fenetre principale ───────────────────────────────────────────────────────
async function createWindow(): Promise<void> {
  win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    titleBarStyle: 'hidden',
    backgroundColor: '#1a1a2e',
    icon: join(getWorkspacePath(), 'ui', 'assets', 'AdhamDesktop.ico'),
    webPreferences: {
      // electron-vite compile le preload dans out/preload/, pas out/main/
      preload: join(__dirname, '..', 'preload', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  if (process.env.NODE_ENV === 'development') {
    // electron-vite injecte ELECTRON_RENDERER_URL automatiquement
    const rendererUrl = process.env['ELECTRON_RENDERER_URL'];
    if (rendererUrl) {
      win.loadURL(rendererUrl);
    } else {
      win.loadURL('http://localhost:5173');
    }
    win.webContents.openDevTools({ mode: 'detach' });
  } else {
    win.loadFile(join(__dirname, '../../renderer/index.html'));
  }
}

// ─── IPC handlers ─────────────────────────────────────────────────────────────
function registerIpc(): void {
  // MCP
  ipcMain.handle('mcp:call', async (_event, tool: string, args: object) => {
    if (!bridge) throw new Error('McpBridge non initialise');
    return bridge.call('tools/call', { name: tool, arguments: args });
  });

  ipcMain.handle('mcp:status', () => bridge?.getStatus() ?? { status: 'disconnected' });

  ipcMain.handle('server:restart', async () => {
    await bridge?.restart();
    return bridge?.getStatus();
  });

  ipcMain.handle('server:stop', async () => { await bridge?.stop(); });

  // Window controls
  ipcMain.on('window-control', (_event, action: string) => {
    if (!win) return;
    if (action === 'minimize') win.minimize();
    if (action === 'maximize') win.isMaximized() ? win.unmaximize() : win.maximize();
    if (action === 'close') win.close();
  });

  // Filesystem workspace (whitelist lecture + écriture)
  ipcMain.handle('fs:readWorkspaceFile', async (_event, relPath: string) => {
    if (relPath.includes('..') || relPath.startsWith('/') || /[A-Za-z]:/.test(relPath)) {
      throw new Error('Chemin non autorise');
    }
    const fullPath = join(getWorkspacePath(), relPath);
    return readFileSync(fullPath, 'utf-8');
  });

  // BUGFIX écriture locale : expose writeWorkspaceFile pour l'UI
  // Sécurité : relPath doit être relatif au workspace, pas de traversal ni de chemin absolu.
  ipcMain.handle('fs:writeWorkspaceFile', async (_event, relPath: string, content: string) => {
    if (relPath.includes('..') || relPath.startsWith('/') || /[A-Za-z]:/.test(relPath)) {
      throw new Error('Chemin non autorise');
    }
    const fullPath = join(getWorkspacePath(), relPath);
    // Créer les dossiers parents si nécessaires
    const { dirname } = await import('path');
    mkdirSync(dirname(fullPath), { recursive: true });
    writeFileSync(fullPath, content, 'utf-8');
    return { ok: true, path: fullPath };
  });

  // Sessions
  ipcMain.handle('sessions:save', (_event, sessions: unknown[]) => {
    writeFileSync(join(getSessionsDir(), 'index.json'), JSON.stringify({ sessions }), 'utf-8');
  });
  ipcMain.handle('sessions:load', () => {
    const p = join(getSessionsDir(), 'index.json');
    if (!existsSync(p)) return { sessions: [] };
    return JSON.parse(readFileSync(p, 'utf-8'));
  });
  ipcMain.handle('session:saveMessages', (_event, sessionId: string, messages: unknown[]) => {
    writeFileSync(join(getSessionsDir(), `${sessionId}.json`), JSON.stringify({ messages }), 'utf-8');
  });
  ipcMain.handle('session:loadMessages', (_event, sessionId: string) => {
    const p = join(getSessionsDir(), `${sessionId}.json`);
    if (!existsSync(p)) return { messages: [] };
    return JSON.parse(readFileSync(p, 'utf-8'));
  });

  // Settings
  ipcMain.handle('settings:save', (_event, settings: object) => { store.set('settings', settings); });
  ipcMain.handle('settings:load', () => store.get('settings') ?? null);

  // Dialog
  ipcMain.handle('dialog:browseDirectory', async () => {
    if (!win) return null;
    const result = await dialog.showOpenDialog(win, { properties: ['openDirectory'] });
    return result.filePaths[0] ?? null;
  });

  // Detection Python
  ipcMain.handle('settings:detectPython', () => {
    const ws = getWorkspacePath();
    const candidates = [
      join(ws, 'venv', 'Scripts', 'python.exe'),
      join(ws, 'venv', 'bin', 'python'),
    ];
    for (const c of candidates) { if (existsSync(c)) return c; }
    return null;
  });

  // Sauvegarde generique depuis les stores
  ipcMain.handle('lcca:saveSettings', (_event, settings: object) => { store.set('settings', settings); });
  ipcMain.handle('lcca:loadSettings', () => store.get('settings') ?? null);
  ipcMain.handle('lcca:saveSessions', (_event, sessions: unknown[]) => {
    writeFileSync(join(getSessionsDir(), 'index.json'), JSON.stringify({ sessions }), 'utf-8');
  });
  ipcMain.handle('lcca:loadSessions', () => {
    const p = join(getSessionsDir(), 'index.json');
    if (!existsSync(p)) return { sessions: [] };
    return JSON.parse(readFileSync(p, 'utf-8'));
  });
  ipcMain.handle('lcca:saveSessionMessages', (_event, sessionId: string, messages: unknown[]) => {
    writeFileSync(join(getSessionsDir(), `${sessionId}.json`), JSON.stringify({ messages }), 'utf-8');
  });
  ipcMain.handle('lcca:loadSessionMessages', (_event, sessionId: string) => {
    const p = join(getSessionsDir(), `${sessionId}.json`);
    if (!existsSync(p)) return { messages: [] };
    return JSON.parse(readFileSync(p, 'utf-8'));
  });

  // V9-06 : lecture des métriques tok/s depuis telemetry.jsonl
  ipcMain.handle('telemetry:readTps', (_event, n: number = 50) => {
    try {
      const telPath = join(getWorkspacePath(), 'logs', 'telemetry.jsonl');
      if (!existsSync(telPath)) return { avg: null, last: null, model: null, count: 0 };
      const lines = readFileSync(telPath, 'utf-8')
        .split('\n')
        .filter(Boolean)
        .slice(-n * 3); // on lit plus large pour filtrer
      const entries: { value: number; labels: { model?: string } }[] = [];
      for (const line of lines) {
        try {
          const obj = JSON.parse(line);
          if (obj.metric === 'llm_tokens_per_sec' && typeof obj.value === 'number') {
            entries.push(obj);
          }
        } catch { /* ignore */ }
      }
      const recent = entries.slice(-n);
      if (recent.length === 0) return { avg: null, last: null, model: null, count: 0 };
      const avg   = recent.reduce((s, e) => s + e.value, 0) / recent.length;
      const last  = recent[recent.length - 1].value;
      const model = recent[recent.length - 1].labels?.model ?? null;
      return { avg: Math.round(avg * 10) / 10, last: Math.round(last * 10) / 10, model, count: recent.length };
    } catch (err) {
      console.error('[main] telemetry:readTps error:', err);
      return { avg: null, last: null, model: null, count: 0 };
    }
  });

  // V9-09 : historique complet des points tok/s pour TelemetryPanel
  ipcMain.handle('telemetry:readHistory', (_event, n: number = 100) => {
    try {
      const telPath = join(getWorkspacePath(), 'logs', 'telemetry.jsonl');
      if (!existsSync(telPath)) return { points: [], model: null };
      const lines = readFileSync(telPath, 'utf-8')
        .split('\n')
        .filter(Boolean);
      const points: { ts: number; value: number; model: string | null }[] = [];
      for (const line of lines) {
        try {
          const obj = JSON.parse(line);
          if (obj.metric === 'llm_tokens_per_sec' && typeof obj.value === 'number') {
            points.push({
              ts:    typeof obj.ts === 'number' ? obj.ts : Date.now(),
              value: Math.round(obj.value * 10) / 10,
              model: obj.labels?.model ?? null,
            });
          }
        } catch { /* ignore */ }
      }
      const recent = points.slice(-n);
      const model  = recent.length > 0 ? recent[recent.length - 1].model : null;
      return { points: recent, model };
    } catch (err) {
      console.error('[main] telemetry:readHistory error:', err);
      return { points: [], model: null };
    }
  });

  // SI-06 : état du système SelfImprove
  ipcMain.handle('si:getStatus', () => {
    try {
      const siDir = join(getWorkspacePath(), 'SelfImprove');
      // Lire config.toml pour le coupling_mode
      const configPath = join(siDir, 'config.toml');
      let coupling_mode = 2;
      if (existsSync(configPath)) {
        const raw = readFileSync(configPath, 'utf-8');
        const m = raw.match(/coupling_mode\s*=\s*(\d)/);
        if (m) coupling_mode = parseInt(m[1], 10);
      }
      // Lire auto_fix_whitelist.json pour auto_fix_enabled
      const wlPath = join(siDir, 'auto_fix_whitelist.json');
      let auto_fix_enabled = false;
      if (existsSync(wlPath)) {
        try {
          const wl = JSON.parse(readFileSync(wlPath, 'utf-8'));
          auto_fix_enabled = Array.isArray(wl) ? wl.length > 0 : false;
        } catch { /* ignore */ }
      }
      // Dernière observation
      const obsDir = join(siDir, 'observations');
      let last_obs_ts: number | null = null;
      if (existsSync(obsDir)) {
        const files = require('fs').readdirSync(obsDir)
          .filter((f: string) => f.endsWith('.json'))
          .sort();
        if (files.length > 0) {
          const last = files[files.length - 1] as string;
          try {
            const obs = JSON.parse(readFileSync(join(obsDir, last), 'utf-8'));
            last_obs_ts = obs.ts ?? null;
          } catch { /* ignore */ }
        }
      }
      // Suggestions en attente
      const pendingPath = join(siDir, 'pending_actions.json');
      let pending_count = 0;
      if (existsSync(pendingPath)) {
        try {
          const pending = JSON.parse(readFileSync(pendingPath, 'utf-8'));
          pending_count = Array.isArray(pending) ? pending.filter((a: { status?: string }) => a.status === 'pending').length : 0;
        } catch { /* ignore */ }
      }
      return {
        coupling_mode,
        auto_fix_enabled,
        observer_active:      coupling_mode >= 1,
        orchestrator_active:  coupling_mode >= 2,
        last_obs_ts,
        pending_count,
      };
    } catch (err) {
      console.error('[main] si:getStatus error:', err);
      return { coupling_mode: 1, auto_fix_enabled: false, observer_active: false, orchestrator_active: false, last_obs_ts: null, pending_count: 0 };
    }
  });

  // SI-06 : N dernières lignes du write-ahead log actions.log
  ipcMain.handle('si:getHistory', (_event, limit: number = 5) => {
    try {
      const logPath = join(getWorkspacePath(), 'SelfImprove', 'actions.log');
      if (!existsSync(logPath)) return [];
      const lines = readFileSync(logPath, 'utf-8')
        .split('\n')
        .filter(Boolean)
        .slice(-limit);
      return lines.map(line => {
        const parts = line.split(',');
        return {
          timestamp: parts[0] ?? '',
          rule_id:   parts[1] ?? '',
          action:    parts[2] ?? '',
          status:    parts[3]?.trim() ?? '',
        };
      });
    } catch (err) {
      console.error('[main] si:getHistory error:', err);
      return [];
    }
  });

  // ROUTER-04 : online models — config + clés API + test connexion
  ipcMain.handle('onlineModels:getConfig', () => {
    try {
      const cfgPath = join(getWorkspacePath(), 'online_models.json');
      if (!existsSync(cfgPath)) return { providers: [], routing: { enabled: false } };
      const raw = readFileSync(cfgPath, 'utf-8');
      const cfg = JSON.parse(raw);
      // Ajoute le statut clé (has_key) sans exposer la valeur réelle
      const providers = (cfg.providers ?? []).map((p: Record<string, unknown>) => ({
        ...p,
        has_key: !!(store.get(`online_model_keys.${p.id}`) as string),
      }));
      return { providers, routing: cfg.routing ?? {} };
    } catch (err) {
      console.error('[main] onlineModels:getConfig error:', err);
      return { providers: [], routing: { enabled: false } };
    }
  });

  ipcMain.handle('onlineModels:setEnabled', (_event, providerId: string, enabled: boolean) => {
    try {
      const cfgPath = join(getWorkspacePath(), 'online_models.json');
      const cfg = JSON.parse(readFileSync(cfgPath, 'utf-8'));
      cfg.providers = (cfg.providers ?? []).map((p: Record<string, unknown>) =>
        p.id === providerId ? { ...p, online: enabled } : p
      );
      // Ecriture atomique T-14
      const tmp = cfgPath + '.tmp';
      writeFileSync(tmp, JSON.stringify(cfg, null, 2), 'utf-8');
      require('fs').renameSync(tmp, cfgPath);
      return { ok: true };
    } catch (err) {
      console.error('[main] onlineModels:setEnabled error:', err);
      return { ok: false, error: String(err) };
    }
  });

  ipcMain.handle('onlineModels:setRoutingEnabled', (_event, enabled: boolean) => {
    try {
      const cfgPath = join(getWorkspacePath(), 'online_models.json');
      const cfg = JSON.parse(readFileSync(cfgPath, 'utf-8'));
      cfg.routing = { ...(cfg.routing ?? {}), enabled };
      const tmp = cfgPath + '.tmp';
      writeFileSync(tmp, JSON.stringify(cfg, null, 2), 'utf-8');
      require('fs').renameSync(tmp, cfgPath);
      return { ok: true };
    } catch (err) {
      console.error('[main] onlineModels:setRoutingEnabled error:', err);
      return { ok: false, error: String(err) };
    }
  });

  // Clé API : stockée dans electron-store — jamais sur disque, jamais dans le renderer
  ipcMain.handle('onlineModels:setKey', (_event, providerId: string, key: string) => {
    store.set(`online_model_keys.${providerId}`, key);
    return { ok: true };
  });

  // Test de connexion — appel HTTP minimal depuis main, clé lue ici seulement
  ipcMain.handle('onlineModels:testProvider', async (_event, providerId: string) => {
    try {
      const cfgPath = join(getWorkspacePath(), 'online_models.json');
      const cfg = JSON.parse(readFileSync(cfgPath, 'utf-8'));
      const provider = (cfg.providers ?? []).find((p: Record<string, unknown>) => p.id === providerId);
      if (!provider) return { ok: false, error: 'Provider inconnu' };
      const apiKey = store.get(`online_model_keys.${providerId}`) as string | undefined;
      if (!apiKey) return { ok: false, error: 'Cle API manquante' };
      const t0 = Date.now();
      const resp = await fetch(provider.api_url as string, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`,
          ...(providerId.startsWith('openrouter') ? { 'HTTP-Referer': 'https://lcca.local' } : {}),
        },
        body: JSON.stringify({
          model:      provider.model_name,
          messages:   [{ role: 'user', content: 'ping' }],
          max_tokens: 1,
        }),
        signal: AbortSignal.timeout((provider.timeout_sec as number ?? 15) * 1000),
      });
      const latency_ms = Date.now() - t0;
      if (!resp.ok) return { ok: false, error: `HTTP ${resp.status}`, latency_ms };
      return { ok: true, latency_ms };
    } catch (err) {
      return { ok: false, error: String(err), latency_ms: 0 };
    }
  });

  // SI-06 : exécuter une commande lcca_si.py (observe, decide, mode X...)
  ipcMain.handle('si:runCommand', (_event, command: string) => {
    return new Promise<{ stdout: string; stderr: string; exitCode: number }>(resolve => {
      const ws  = getWorkspacePath();
      const py  = join(ws, 'venv', 'Scripts', 'python.exe');
      const script = join(ws, 'lcca_si.py');
      const args   = command.trim().split(/\s+/);
      const proc   = spawn(py, [script, ...args], { cwd: ws });
      let stdout = '', stderr = '';
      const timer = setTimeout(() => { proc.kill(); }, 10_000); // SI_TIMEOUT
      proc.stdout.on('data', (d: Buffer) => { stdout += d.toString(); });
      proc.stderr.on('data', (d: Buffer) => { stderr += d.toString(); });
      proc.on('close', (code: number | null) => {
        clearTimeout(timer);
        resolve({ stdout, stderr, exitCode: code ?? -1 });
      });
    });
  });

  // ── PROJ-05 : Mode Projets ────────────────────────────────────────────────────

  /** Répertoire racine des projets LCCA */
  function getProjectsDir(): string {
    return join(getWorkspacePath(), 'projects');
  }

  // Lister les projets (scan filesystem — source de vérité)
  ipcMain.handle('project:list', () => {
    try {
      const { readdirSync, statSync } = require('fs');
      const root = getProjectsDir();
      if (!existsSync(root)) return [];
      const slugs = readdirSync(root).filter((s: string) => {
        try { return statSync(join(root, s)).isDirectory(); } catch { return false; }
      });
      const projects: unknown[] = [];
      for (const slug of slugs) {
        const metaPath = join(root, slug, '.llca', 'project.json');
        if (!existsSync(metaPath)) continue;
        try {
          const meta = JSON.parse(readFileSync(metaPath, 'utf-8'));
          projects.push(meta);
        } catch { /* JSON invalide — ignorer */ }
      }
      // Tri par last_opened décroissant
      projects.sort((a: unknown, b: unknown) => {
        const ta = new Date((a as Record<string,string>).last_opened ?? 0).getTime();
        const tb = new Date((b as Record<string,string>).last_opened ?? 0).getTime();
        return tb - ta;
      });
      return projects;
    } catch (err) {
      console.error('[main] project:list error:', err);
      return [];
    }
  });

  // Ouvrir un projet — met à jour last_opened dans project.json
  ipcMain.handle('project:open', (_event, id: string) => {
    try {
      const root = getProjectsDir();
      const slugs: string[] = require('fs').readdirSync(root);
      for (const slug of slugs) {
        const metaPath = join(root, slug, '.llca', 'project.json');
        if (!existsSync(metaPath)) continue;
        try {
          const meta = JSON.parse(readFileSync(metaPath, 'utf-8'));
          if (meta.id !== id) continue;
          meta.last_opened = new Date().toISOString();
          const tmp = metaPath + '.tmp';
          writeFileSync(tmp, JSON.stringify(meta, null, 2), 'utf-8');
          require('fs').renameSync(tmp, metaPath);
          return { ok: true };
        } catch (e) {
          return { ok: false, error: String(e) };
        }
      }
      return { ok: false, error: 'Projet introuvable' };
    } catch (err) {
      console.error('[main] project:open error:', err);
      return { ok: false, error: String(err) };
    }
  });

  // Créer un projet — structure minimale .llca/project.json
  // PROJ-UI-04 : accepte tags (string[]) + storage_mode ('shared'|'isolated')
  ipcMain.handle('project:create', (_event, name: string, description: string, tags: string[] = [], storageMode: string = 'shared') => {
    try {
      // Générer le slug ASCII
      const raw  = name.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
      let   slug = raw.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
      const root = getProjectsDir();
      mkdirSync(root, { recursive: true });
      // Unicité du slug
      let final = slug;
      let counter = 1;
      while (existsSync(join(root, final))) { final = `${slug}-${counter++}`; }
      const id  = require('crypto').randomUUID ? require('crypto').randomUUID() : `proj-${Date.now()}`;
      const now = new Date().toISOString();
      const validMode = storageMode === 'isolated' ? 'isolated' : 'shared';
      const meta = {
        id, name, slug: final, description,
        status:       'active',
        created_at:   now,
        last_opened:  now,
        storage_mode: validMode,
        tags:         Array.isArray(tags) ? tags.filter(t => typeof t === 'string' && t.trim()) : [],
      };
      const llcaDir = join(root, final, '.llca');
      mkdirSync(llcaDir, { recursive: true });
      // Écriture atomique T-14
      const metaPath = join(llcaDir, 'project.json');
      const tmp = metaPath + '.tmp';
      writeFileSync(tmp, JSON.stringify(meta, null, 2), 'utf-8');
      require('fs').renameSync(tmp, metaPath);
      return { ok: true, project: meta };
    } catch (err) {
      console.error('[main] project:create error:', err);
      return { ok: false, error: String(err) };
    }
  });

  // Archiver un projet — status: 'archived' dans project.json
  ipcMain.handle('project:archive', (_event, id: string) => {
    try {
      const root   = getProjectsDir();
      const slugs: string[] = require('fs').readdirSync(root);
      for (const slug of slugs) {
        const metaPath = join(root, slug, '.llca', 'project.json');
        if (!existsSync(metaPath)) continue;
        try {
          const meta = JSON.parse(readFileSync(metaPath, 'utf-8'));
          if (meta.id !== id) continue;
          meta.status = 'archived';
          const tmp = metaPath + '.tmp';
          writeFileSync(tmp, JSON.stringify(meta, null, 2), 'utf-8');
          require('fs').renameSync(tmp, metaPath);
          return { ok: true };
        } catch (e) {
          return { ok: false, error: String(e) };
        }
      }
      return { ok: false, error: 'Projet introuvable' };
    } catch (err) {
      console.error('[main] project:archive error:', err);
      return { ok: false, error: String(err) };
    }
  });

  // ── PROJ-UI-01 : UserContext read ─────────────────────────────────────────
  // Lit projects/.llca/user_context.json et retourne {name, locale, tone, ...}
  // Mode dégradé silencieux si le fichier est absent.
  ipcMain.handle('userctx:read', async () => {
    try {
      const ctxPath = join(getWorkspacePath(), 'projects', '.llca', 'user_context.json');
      const { existsSync, readFileSync } = await import('fs');
      if (!existsSync(ctxPath)) return { ok: true, data: null };
      const raw = readFileSync(ctxPath, 'utf-8');
      return { ok: true, data: JSON.parse(raw) };
    } catch (err) {
      console.error('[main] userctx:read error:', err);
      return { ok: false, data: null, error: String(err) };
    }
  });

  // ── SETTINGS-PROFILE : écriture du prénom utilisateur ───────────────────────
  // Met à jour identity.name dans user_context.json (action explicite, pas de WAL).
  ipcMain.handle('userctx:setName', async (_event, name: string) => {
    try {
      const llcaDir  = join(getWorkspacePath(), 'projects', '.llca');
      const ctxPath  = join(llcaDir, 'user_context.json');
      mkdirSync(llcaDir, { recursive: true });
      let ctx: Record<string, unknown> = {};
      if (existsSync(ctxPath)) {
        try { ctx = JSON.parse(readFileSync(ctxPath, 'utf-8')); } catch { /* ignore */ }
      }
      const identity = (ctx['identity'] as Record<string, unknown>) ?? {};
      identity['name'] = name.trim();
      ctx['identity']  = identity;
      // Écriture atomique T-14
      const tmp = ctxPath + '.tmp';
      writeFileSync(tmp, JSON.stringify(ctx, null, 2), 'utf-8');
      require('fs').renameSync(tmp, ctxPath);
      return { ok: true };
    } catch (err) {
      console.error('[main] userctx:setName error:', err);
      return { ok: false, error: String(err) };
    }
  });

  // ── VOICE-07 : pipeline voix (STT + TTS) ───────────────────────────────────

  // Processus voice_service.py (STT WebSocket port 8765)
  let voiceProcess: ReturnType<typeof spawn> | null = null;
  // Processus tts_service.py (TTS WebSocket port 8766)
  let ttsProcess: ReturnType<typeof spawn> | null = null;

  /** Chemin vers le venv Voice isolé */
  function getVoicePython(): string {
    return join(getWorkspacePath(), 'Voice', 'venv', 'Scripts', 'python.exe');
  }
  function getVoiceDir(): string {
    return join(getWorkspacePath(), 'Voice');
  }

  // Lancer le service STT
  ipcMain.handle('voice:start', async () => {
    if (voiceProcess) return { ok: true, msg: 'deja demarre' };
    try {
      const py     = getVoicePython();
      const script = join(getVoiceDir(), 'voice_service.py');
      voiceProcess = spawn(py, [script], { cwd: getVoiceDir(), stdio: 'pipe' });
      voiceProcess.on('close', () => { voiceProcess = null; });
      voiceProcess.stderr?.on('data', (d: Buffer) => {
        console.error('[voice_service]', d.toString().trim());
      });
      return { ok: true };
    } catch (err) {
      return { ok: false, error: String(err) };
    }
  });

  // Arrêter le service STT
  ipcMain.handle('voice:stop', async () => {
    if (!voiceProcess) return { ok: true };
    voiceProcess.kill('SIGTERM');
    voiceProcess = null;
    return { ok: true };
  });

  // Statut service STT
  ipcMain.handle('voice:status', async () => {
    return { running: voiceProcess !== null };
  });

  // Lancer le service TTS
  ipcMain.handle('tts:start', async () => {
    if (ttsProcess) return { ok: true, msg: 'deja demarre' };
    try {
      const py     = getVoicePython();
      const script = join(getVoiceDir(), 'tts_service.py');
      ttsProcess = spawn(py, [script], { cwd: getVoiceDir(), stdio: 'pipe' });
      ttsProcess.on('close', () => { ttsProcess = null; });
      ttsProcess.stderr?.on('data', (d: Buffer) => {
        console.error('[tts_service]', d.toString().trim());
      });
      return { ok: true };
    } catch (err) {
      return { ok: false, error: String(err) };
    }
  });

  // Arrêter le service TTS
  ipcMain.handle('tts:stop', async () => {
    if (!ttsProcess) return { ok: true };
    ttsProcess.kill('SIGTERM');
    ttsProcess = null;
    return { ok: true };
  });

  // Statut service TTS
  ipcMain.handle('tts:status', async () => {
    return { running: ttsProcess !== null };
  });

  // Tuer proprement les deux services à la fermeture de l'application
  app.on('before-quit', () => {
    voiceProcess?.kill('SIGTERM');
    ttsProcess?.kill('SIGTERM');
  });
}

// ─── Demarrage ────────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  registerIpc();

  bridge = new McpBridge(getWorkspacePath());
  // UI-07 : forwarder les tokens de streaming vers le renderer
  bridge.onToken((reqId, token) => {
    win?.webContents.send('lcca:token', { reqId, token });
  });
  try {
    await bridge.start();
  } catch (err) {
    console.error('[main] McpBridge start failed:', err);
  }

  await createWindow();
});

app.on('window-all-closed', async () => {
  try { await bridge?.stop(); } catch { /* ignore */ }
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', async () => {
  if (BrowserWindow.getAllWindows().length === 0) await createWindow();
});
