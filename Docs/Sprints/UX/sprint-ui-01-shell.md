# Sprint UI-01 — Shell Electron + Layout + Chat basique
<!-- AI-READY | Sprint UI-01 | Version 1.0.0 | 2026-04-18 -->

## Contexte & objectif

Premier sprint UI : bootstrapper le projet Electron, câbler le MCP Bridge vers le
McpServer Python existant, et livrer un chat minimaliste mais fonctionnel — on peut
taper une commande, l'envoyer au serveur, lire la réponse. Tout le reste est vide
ou stub. C'est le socle que tous les sprints suivants étendent.

**Prérequis** : McpServer V7.2 opérationnel (`D:\LLMCodeAgent\core\mcp_server.py`).
**Livrable** : `npm run dev` lance une fenêtre Electron avec chat fonctionnel MCP.
**Cible** : ~500 lignes TypeScript/TSX réelles, 0 test unitaire (Sprint UI-03 les ajoute).

---

## Périmètre

| # | Fichier | Type | Description |
|---|---------|------|-------------|
| 1 | `ui/package.json` | CREATE | Dépendances npm (electron, react, vite…) |
| 2 | `ui/electron-vite.config.ts` | CREATE | Config build |
| 3 | `ui/tsconfig.json` | CREATE | Config TypeScript |
| 4 | `ui/electron/main.ts` | CREATE | Main process Electron |
| 5 | `ui/electron/preload.ts` | CREATE | Context bridge `window.lcca` |
| 6 | `ui/electron/mcp-bridge.ts` | CREATE | Subprocess McpServer + JSON-RPC |
| 7 | `ui/src/styles/globals.css` | CREATE | CSS Variables dark (thème défaut) |
| 8 | `ui/src/styles/reset.css` | CREATE | Reset CSS minimal |
| 9 | `ui/src/types/mcp.ts` | CREATE | Types McpResult, McpStatus, McpEvent… |
| 10 | `ui/src/types/chat.ts` | CREATE | Types Session, Message, TxBadge |
| 11 | `ui/src/stores/chatStore.ts` | CREATE | Zustand — sessions + messages + streaming |
| 12 | `ui/src/stores/contextStore.ts` | CREATE | Zustand — mcpStatus + stub workspace |
| 13 | `ui/src/stores/settingsStore.ts` | CREATE | Zustand — thème + workspacePath |
| 14 | `ui/src/hooks/useMcp.ts` | CREATE | Hook `call()` + wrappers tools |
| 15 | `ui/src/components/TitleBar.tsx` | CREATE | Barre titre custom draggable |
| 16 | `ui/src/components/Layout.tsx` | CREATE | Grid 3 panneaux (sidebar/chat/context) |
| 17 | `ui/src/components/Sidebar.tsx` | CREATE | Sidebar icônes (stub session list) |
| 18 | `ui/src/components/ChatPanel.tsx` | CREATE | MessageList + InputZone |
| 19 | `ui/src/components/MessageBubble.tsx` | CREATE | Bulles user/assistant (texte brut) |
| 20 | `ui/src/components/InputZone.tsx` | CREATE | TextArea + SendButton |
| 21 | `ui/src/components/ContextPanel.tsx` | CREATE | Panel droit (stub, juste McpStatusBar) |
| 22 | `ui/src/App.tsx` | CREATE | Racine React |
| 23 | `ui/src/main.tsx` | CREATE | Entrée React |

---

## Tâche 1 — Scaffolding projet

### 1.1 `ui/package.json`

```json
{
  "name": "lcca-desktop",
  "version": "1.0.0",
  "private": true,
  "main": "dist-electron/main.js",
  "scripts": {
    "dev":   "electron-vite dev",
    "build": "electron-vite build",
    "dist":  "npm run build && electron-builder"
  },
  "dependencies": {
    "electron":         "^29.0.0",
    "react":            "^18.3.0",
    "react-dom":        "^18.3.0",
    "zustand":          "^4.5.0",
    "react-markdown":   "^9.0.0",
    "rehype-highlight": "^7.0.0",
    "rehype-sanitize":  "^6.0.0",
    "highlight.js":     "^11.9.0",
    "lucide-react":     "^0.383.0",
    "uuid":             "^9.0.0"
  },
  "devDependencies": {
    "electron-vite":    "^2.3.0",
    "electron-builder": "^24.0.0",
    "@types/node":      "^20.0.0",
    "@types/react":     "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@types/uuid":      "^9.0.0",
    "typescript":       "^5.4.0",
    "vite":             "^5.2.0"
  }
}
```

### 1.2 `ui/electron-vite.config.ts`

```typescript
import { defineConfig } from 'electron-vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  main: {
    build: { outDir: 'dist-electron', rollupOptions: { input: { main: resolve(__dirname, 'electron/main.ts') } } }
  },
  preload: {
    build: { outDir: 'dist-electron', rollupOptions: { input: { preload: resolve(__dirname, 'electron/preload.ts') } } }
  },
  renderer: {
    root: 'src',
    build: { outDir: 'dist-renderer' },
    plugins: [react()],
  },
});
```

### 1.3 `ui/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["electron/**/*", "src/**/*"]
}
```

---

## Tâche 2 — Main process & sécurité

### 2.1 `ui/electron/main.ts`

Responsabilités :
- Créer la `BrowserWindow` (1280×800, min 900×600, frame: false)
- Charger l'URL renderer (dev: localhost:5173, prod: dist-renderer/index.html)
- Instancier `McpBridge` et l'exposer via `ipcMain`
- Gérer les événements window-control (`minimize`, `maximize`, `close`)
- Démarrer le McpServer si `autoStartServer = true`

```typescript
// electron/main.ts — structure cible
import { app, BrowserWindow, ipcMain, dialog } from 'electron';
import { join } from 'path';
import { McpBridge } from './mcp-bridge';

let win: BrowserWindow | null = null;
let bridge: McpBridge | null = null;

async function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 800, minWidth: 900, minHeight: 600,
    frame: false,          // TitleBar custom
    titleBarStyle: 'hidden',
    backgroundColor: '#1a1a2e',
    webPreferences: {
      preload: join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  if (process.env.NODE_ENV === 'development') {
    win.loadURL('http://localhost:5173');
  } else {
    win.loadFile(join(__dirname, '../dist-renderer/index.html'));
  }
}

app.whenReady().then(async () => {
  bridge = new McpBridge();
  await bridge.start();

  // IPC : tool call MCP
  ipcMain.handle('mcp:call', async (_event, tool: string, args: object) => {
    return bridge!.call('tools/call', { name: tool, arguments: args });
  });

  // IPC : status
  ipcMain.handle('mcp:status', () => bridge!.getStatus());

  // IPC : lifecycle serveur
  ipcMain.handle('server:restart', () => bridge!.restart());
  ipcMain.handle('server:stop',    () => bridge!.stop());

  // IPC : window controls
  ipcMain.on('window-control', (_event, action: string) => {
    if (!win) return;
    if (action === 'minimize') win.minimize();
    if (action === 'maximize') win.isMaximized() ? win.unmaximize() : win.maximize();
    if (action === 'close') win.close();
  });

  // IPC : lecture fichier workspace (whitelist)
  ipcMain.handle('fs:readWorkspaceFile', async (_event, relPath: string) => {
    // Validation : relPath ne doit pas contenir '..' (sécurité)
    if (relPath.includes('..') || relPath.startsWith('/') || relPath.includes(':')) {
      throw new Error('Chemin non autorisé');
    }
    const { readFileSync } = await import('fs');
    const { join: pathJoin } = await import('path');
    const workspace = 'D:\\LLMCodeAgent'; // à lire depuis settingsStore persisté
    return readFileSync(pathJoin(workspace, relPath), 'utf-8');
  });

  await createWindow();
});

app.on('window-all-closed', () => {
  bridge?.stop().catch(() => {});
  if (process.platform !== 'darwin') app.quit();
});
```

### 2.2 `ui/electron/preload.ts`

Expose `window.lcca` via `contextBridge` — interface complète définie dans
`spec-ui-02-architecture.md` section 3.2.

```typescript
import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('lcca', {
  // MCP
  mcpCall:   (tool: string, args: object) => ipcRenderer.invoke('mcp:call', tool, args),
  mcpStatus: ()                           => ipcRenderer.invoke('mcp:status'),

  // Lifecycle
  restartServer: () => ipcRenderer.invoke('server:restart'),
  stopServer:    () => ipcRenderer.invoke('server:stop'),

  // Events
  onServerStatus: (cb: (s: unknown) => void) => {
    const handler = (_: unknown, s: unknown) => cb(s);
    ipcRenderer.on('server:status', handler);
    return () => ipcRenderer.off('server:status', handler);
  },

  // Filesystem (limité)
  readWorkspaceFile: (relPath: string) => ipcRenderer.invoke('fs:readWorkspaceFile', relPath),
});
```

### 2.3 `ui/electron/mcp-bridge.ts`

Gestion complète du subprocess Python.

**Points d'implémentation critiques** :
- Spawn : `spawn(pythonExe, [mcpScript], { stdio: ['pipe','pipe','pipe'] })`
  — `pythonExe` = valeur lue depuis `settings.json` ou auto-détectée
  — jamais `shell: true`
- Lecture stdout : `readline` sur `proc.stdout` → parse JSON → dispatch `pending`
- Write stdin : `proc.stdin.write(JSON.stringify(request) + '\n')`
- Timeout par requête : 30 000ms — rejette avec `McpTimeoutError`
- Reconnexion automatique : `onCrash()` → backoff 1s / 2s / 5s, max 3 tentatives

```typescript
// Squelette mcp-bridge.ts
import { spawn, ChildProcess } from 'child_process';
import * as readline from 'readline';
import { join } from 'path';

interface PendingRequest {
  resolve: (v: unknown) => void;
  reject:  (e: Error)   => void;
  timer:   NodeJS.Timeout;
}

export class McpBridge {
  private proc: ChildProcess | null = null;
  private rl: readline.Interface | null = null;
  private pending = new Map<number, PendingRequest>();
  private requestId = 0;
  private status: 'connecting' | 'connected' | 'disconnected' | 'error' = 'disconnected';
  private retryCount = 0;
  private readonly RETRY_DELAYS = [1000, 2000, 5000];
  private readonly TIMEOUT_MS = 30_000;

  async start(): Promise<void> {
    this.status = 'connecting';
    // Trouver python (variable env ou chemin venv)
    const pythonExe = process.env.LCCA_PYTHON ?? join('D:\\LLMCodeAgent', 'venv', 'Scripts', 'python.exe');
    const mcpScript = join('D:\\LLMCodeAgent', 'core', 'mcp_server.py');

    this.proc = spawn(pythonExe, [mcpScript], {
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });

    this.rl = readline.createInterface({ input: this.proc.stdout! });
    this.rl.on('line', (line) => this.onLine(line));
    this.proc.on('close', (code) => this.onCrash(code));

    // Attendre le message "lcca ready"
    await this.initialize();
    this.status = 'connected';
    this.retryCount = 0;
  }

  private async initialize(): Promise<void> {
    // initialize JSON-RPC
    const result = await this.call('initialize', {
      protocolVersion: '2024-11-05',
      clientInfo: { name: 'lcca-desktop', version: '1.0.0' },
      capabilities: {},
    }) as { protocolVersion: string };
    // notifications/initialized (no reply expected)
    this.send({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} });
  }

  async call(method: string, params: object): Promise<unknown> {
    const id = ++this.requestId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`MCP timeout [${method}] after ${this.TIMEOUT_MS}ms`));
      }, this.TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      this.send({ jsonrpc: '2.0', id, method, params });
    });
  }

  private send(obj: object): void {
    if (!this.proc?.stdin?.writable) throw new Error('McpBridge: stdin non disponible');
    this.proc.stdin.write(JSON.stringify(obj) + '\n');
  }

  private onLine(line: string): void {
    try {
      const msg = JSON.parse(line) as { id?: number; result?: unknown; error?: unknown };
      if (msg.id !== undefined) {
        const pending = this.pending.get(msg.id);
        if (pending) {
          clearTimeout(pending.timer);
          this.pending.delete(msg.id);
          if (msg.error) pending.reject(new Error(JSON.stringify(msg.error)));
          else pending.resolve(msg.result);
        }
      }
    } catch {
      // Ligne non-JSON (logs Python) → ignorer
    }
  }

  private onCrash(code: number | null): void {
    this.status = 'error';
    if (this.retryCount < this.RETRY_DELAYS.length) {
      const delay = this.RETRY_DELAYS[this.retryCount++];
      setTimeout(() => this.start().catch(() => {}), delay);
    }
  }

  async stop(): Promise<void> {
    this.proc?.stdin?.end();
    await new Promise<void>((res) => {
      const t = setTimeout(() => { this.proc?.kill('SIGKILL'); res(); }, 3000);
      this.proc?.on('close', () => { clearTimeout(t); res(); });
    });
  }

  async restart(): Promise<void> {
    await this.stop();
    this.retryCount = 0;
    await this.start();
  }

  getStatus() { return { status: this.status }; }
}
```

---

## Tâche 3 — Types TypeScript

### 3.1 `ui/src/types/mcp.ts`

Copier intégralement les types de `spec-ui-03-composants.md` section 10 :
`McpResult`, `GenerateSpecResult`, `ValidateSpecResult`, `ViolationEntry`,
`MemorySearchResult`, `MemoryEntry`, `EditBatchResult`, `SandboxResult`,
`McpStatus`, `McpEvent`, `StreamToken`.

Ajouter :
```typescript
export class McpError extends Error {
  constructor(public code: number, message: string) { super(message); }
}
```

### 3.2 `ui/src/types/chat.ts`

```typescript
export interface Session {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}

export interface TxBadge {
  txId: string;
  files: string[];
  status: 'committed' | 'rolled_back' | 'partial';
  timestamp: string;
}

export interface SpecBadge {
  specId: string;
  title: string;
  domain: string;
  validated: boolean;
  score: number;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  createdAt: string;
  txBadge?:   TxBadge;
  specBadge?: SpecBadge;
}
```

---

## Tâche 4 — Stores Zustand

Implémenter les 3 stores selon `spec-ui-02-architecture.md` section 4.
Sprint UI-01 : implémenter les interfaces complètes mais les actions `refresh*()`
peuvent être des stubs qui ne font rien (remplis en UI-03).

**`chatStore.ts`** : priorité maximale — `appendMessage`, `appendStreamToken`,
`finalizeStream`, `createSession` doivent fonctionner dès ce sprint.

**`settingsStore.ts`** : `persist()` / `load()` utilisent `localStorage` Electron
(via `ipcRenderer.invoke('settings:save/load')` en V2, pour l'instant `localStorage`
du renderer suffit en dev).

---

## Tâche 5 — Hook useMcp

### `ui/src/hooks/useMcp.ts`

```typescript
import { useCallback } from 'react';
import { McpError } from '../types/mcp';
import type { GenerateSpecResult, ValidateSpecResult, EditBatchResult, SandboxResult } from '../types/mcp';

export function useMcp() {
  const call = useCallback(async <T>(tool: string, args: Record<string, unknown>): Promise<T> => {
    const result = await (window as any).lcca.mcpCall(tool, args) as any;
    if (result?.error) throw new McpError(result.error.code, result.error.message);
    const text = result?.content?.[0]?.text;
    if (!text) throw new McpError(-32603, 'Réponse MCP vide');
    return JSON.parse(text) as T;
  }, []);

  return {
    generateSpec: (intent: string, domain: string) =>
      call<GenerateSpecResult>('generate_spec', { intent, domain }),
    validateSpec: (specId?: string, bodyMd?: string) =>
      call<ValidateSpecResult>('validate_spec', { spec_id: specId, body_md: bodyMd }),
    editBatch: (files: unknown[]) =>
      call<EditBatchResult>('edit_batch', { files }),
    sandboxRun: (code: string) =>
      call<SandboxResult>('sandbox_run', { code }),
    memorySearch: (query: string, n = 5) =>
      call<Record<string, unknown[]>>('memory_search', { query, n }),
  };
}
```

---

## Tâche 6 — Composants UI (sprint UI-01 — version minimale)

### Design System — `globals.css`

Implémenter les CSS Variables dark complètes de `spec-ui-01-vision.md` section 3.2.
Ajouter :
```css
body { background: var(--bg-primary); color: var(--text-primary);
       font-family: var(--font-sans); font-size: var(--font-size-base); }
* { box-sizing: border-box; margin: 0; padding: 0; }
```

### `TitleBar.tsx` — version complète

Implémenter selon `spec-ui-03-composants.md` section 2 :
- Zone draggable CSS
- Indicateurs MCP + Ollama depuis `contextStore`
- Boutons thème / settings / window controls

### `Layout.tsx`

```tsx
// Grid CSS 3 colonnes : sidebar(52px) | chat(flex) | context(280px)
// Collapse context si panelMode === 'compact' ou 'focus'
export function Layout() {
  const { panelMode } = useSettingsStore();
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `52px 1fr ${panelMode === 'standard' ? '280px' : '0'}`,
                  height: '100vh', overflow: 'hidden' }}>
      <Sidebar />
      <ChatPanel />
      {panelMode === 'standard' && <ContextPanel />}
    </div>
  );
}
```

### `ChatPanel.tsx`

Contient `MessageList` + `InputZone`. Gère le scroll automatique (useRef + useEffect
sur `messages.length`). Vide state (écran d'accueil) si `messages.length === 0`.

### `MessageBubble.tsx` — Sprint UI-01 : texte brut uniquement

Markdown et CodeBlock ajoutés en Sprint UI-02. Pour l'instant :
```tsx
// Bulle user : alignée droite, fond accent-soft
// Bulle assistant : alignée gauche, avatar ⬡, fond bg-surface
// Contenu : <p>{message.content}</p> (pas encore de Markdown)
```

### `InputZone.tsx`

- `<textarea>` auto-resize (onInput : ajuster height selon scrollHeight)
- `Enter` → `onSend`, `Shift+Enter` → saut de ligne
- `SendButton` : désactivé si `isStreaming` ou input vide
- Appel `useMcp()` depuis le parent `ChatPanel`, pas depuis InputZone directement

### `ContextPanel.tsx` — Sprint UI-01 : stub

Pour l'instant : juste `McpStatusBar` (indicateur MCP + bouton redémarrer).
Les sections Workspace/Specs/TX sont ajoutées en UI-03.

### `Sidebar.tsx` — Sprint UI-01 : icônes uniquement

3 icônes (💬 Sessions, ⚙ Settings, ? Aide) en colonne, sans fonctionnalité réelle.

---

## Tâche 7 — Flux complet message → réponse

Dans `ChatPanel.tsx`, implémenter le handler `handleSend` :

```typescript
async function handleSend(text: string) {
  if (!text.trim() || isStreaming) return;

  // 1. Ajouter le message user
  const userMsg: Message = { id: uuid(), role: 'user', content: text, createdAt: new Date().toISOString() };
  appendMessage(userMsg);
  setIsStreaming(true);

  try {
    // 2. Appel MCP — pour l'instant: memory_search comme proxy de "chat"
    // Sprint UI-02 : remplacer par le vrai routing (NL → MCP tools)
    const result = await mcp.memorySearch(text, 3);

    // 3. Construire réponse assistant (formatée)
    const responseText = formatMcpResponse(result);

    // 4. Simuler streaming (15ms/token)
    await simulateStreaming(responseText, appendStreamToken);
    finalizeStream();

  } catch (err) {
    const errMsg: Message = {
      id: uuid(), role: 'system',
      content: `⚠ Erreur MCP : ${(err as Error).message}`,
      createdAt: new Date().toISOString(),
    };
    appendMessage(errMsg);
  } finally {
    setIsStreaming(false);
  }
}

// Simulation streaming côté renderer (spec UI-02 section 3.4)
async function simulateStreaming(text: string, appendToken: (t: string) => void) {
  const tokens = text.split(/(?<=\s)/); // split sur espaces en conservant le délimiteur
  for (const token of tokens) {
    appendToken(token);
    await new Promise(r => setTimeout(r, 15));
  }
}
```

---

## Critères d'acceptance Sprint UI-01

| Critère | Validation |
|---------|-----------|
| `npm run dev` lance sans erreur | Manuel |
| Fenêtre Electron s'ouvre (frame custom) | Manuel |
| Indicateur MCP = ● Connecté après démarrage | Manuel |
| Taper une commande + Enter → bulle user apparaît | Manuel |
| Réponse MCP apparaît en bulle assistant | Manuel |
| Streaming simulé visible (tokens progressifs) | Manuel |
| Erreur MCP affichée en bulle système | Manuel |
| Boutons `-` `□` `×` fonctionnent | Manuel |
| Toggle thème dark/light fonctionne | Manuel |
| `Ctrl+N` crée une nouvelle session (vide) | Manuel |

---

## Ce qui est explicitement hors scope Sprint UI-01

- Markdown dans les bulles (→ UI-02)
- CodeBlock (→ UI-02)
- TxBadge / SpecBadge (→ UI-02)
- Historique sessions persisté (→ UI-02)
- ContextPanel sections Workspace/Specs/TX (→ UI-03)
- SessionList dans la Sidebar (→ UI-02)
- CommandPalette (→ UI-04)
- SettingsModal (→ UI-05)
- Tests unitaires (→ UI-03)
- Build packaging (→ UI-05)

<!-- AI-READY | Sprint UI-01 Shell Electron + Layout + Chat basique | Version 1.0.0 | 2026-04-18 -->
