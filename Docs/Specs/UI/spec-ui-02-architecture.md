# Spec UI-02 — Architecture Technique
<!-- AI-READY | Architecture LCCA Desktop | Version 1.0.0 | 2026-04-18 -->

## 1. Vue d'ensemble

LCCA Desktop est une application **Electron** encapsulant une interface **React/TypeScript**.
Elle communique avec le backend LCCA via le **McpServer existant** (JSON-RPC 2.0 over stdio)
sans aucune modification du backend Python.

```
┌──────────────────────────────────────────────────────────────────┐
│  ELECTRON MAIN PROCESS                                           │
│  ─────────────────────────────────────────────────────────────  │
│  ┌──────────────┐    ┌─────────────────────────────────────┐   │
│  │  MCP Bridge  │◄──►│  McpServer (Python subprocess)      │   │
│  │  (Node.js)   │    │  D:\LLMCodeAgent\core\mcp_server.py │   │
│  │  JSON-RPC    │    │  stdin/stdout pipes                  │   │
│  └──────┬───────┘    └─────────────────────────────────────┘   │
│         │ IPC (contextBridge)                                    │
└─────────┼────────────────────────────────────────────────────────┘
          │
┌─────────┼────────────────────────────────────────────────────────┐
│  RENDERER PROCESS (React + TypeScript)                           │
│  ─────────────────────────────────────────────────────────────  │
│  ┌──────┴──────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │  useMcp()   │  │  ChatStore  │  │  ContextStore        │   │
│  │  hook IPC   │  │  (Zustand)  │  │  (Zustand)           │   │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬───────────┘   │
│         └────────────────┴─────────────────────┘               │
│                          │                                       │
│              ┌───────────▼───────────┐                          │
│              │  React Component Tree │                          │
│              └───────────────────────┘                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Stack technique

### 2.1 Dépendances principales

| Package | Version min | Rôle |
|---------|-------------|------|
| `electron` | 29.x | Shell desktop cross-platform |
| `react` | 18.x | UI framework |
| `typescript` | 5.x | Typage statique |
| `zustand` | 4.x | State management léger |
| `vite` | 5.x | Bundler (avec `electron-vite`) |
| `electron-vite` | 2.x | Build pipeline Electron+Vite |
| `react-markdown` | 9.x | Rendu Markdown dans les bulles |
| `rehype-highlight` | 7.x | Coloration syntaxique code |
| `highlight.js` | 11.x | Backend coloration |
| `lucide-react` | 0.383.x | Icônes |

### 2.2 Dépendances dev

| Package | Rôle |
|---------|------|
| `electron-builder` | Packaging installeur Windows |
| `@types/node` | Typages Node.js côté main |
| `eslint` + `prettier` | Qualité code |

### 2.3 Structure projet (dossier dédié)

```
D:\LLMCodeAgent\ui\
├── electron\
│   ├── main.ts          # Electron main process
│   ├── preload.ts       # Context bridge (sécurité)
│   └── mcp-bridge.ts   # Gestionnaire subprocess McpServer
├── src\
│   ├── main.tsx         # Entrée React
│   ├── App.tsx          # Layout racine + routing
│   ├── stores\
│   │   ├── chatStore.ts       # Sessions, messages, streaming
│   │   ├── contextStore.ts    # Workspace, specs, transactions
│   │   └── settingsStore.ts   # Thème, préférences, persistence
│   ├── hooks\
│   │   ├── useMcp.ts          # Appels JSON-RPC via IPC
│   │   ├── useStreaming.ts     # Streaming tokens
│   │   └── useShortcuts.ts    # Raccourcis clavier globaux
│   ├── components\            # Voir spec-ui-03-composants.md
│   ├── types\
│   │   ├── mcp.ts             # Types JSON-RPC, Tool, ToolResult
│   │   ├── chat.ts            # Message, Session, TxBadge
│   │   └── spec.ts            # SpecEntry, ValidationResult
│   └── styles\
│       ├── globals.css        # CSS Variables (thèmes)
│       └── reset.css
├── package.json
├── electron-vite.config.ts
├── tsconfig.json
└── electron-builder.yml
```

---

## 3. Communication IPC — MCP Bridge

### 3.1 Sécurité Electron
```
contextIsolation: true
nodeIntegration: false   ← OBLIGATOIRE (sécurité)
sandbox: true
```

Seules les méthodes exposées dans `preload.ts` via `contextBridge.exposeInMainWorld`
sont accessibles depuis le renderer. Jamais d'accès direct Node.js depuis React.

### 3.2 Interface preload.ts
```typescript
// Exposée comme window.lcca
interface LccaAPI {
  // MCP tools
  mcpCall(tool: string, args: Record<string, unknown>): Promise<McpResult>;
  mcpStatus(): Promise<McpStatus>;

  // Serveur lifecycle
  startServer(): Promise<void>;
  stopServer(): Promise<void>;
  restartServer(): Promise<void>;

  // Events (renderer → main → renderer)
  onMcpEvent(callback: (event: McpEvent) => void): () => void;
  onServerStatus(callback: (status: McpStatus) => void): () => void;
  onStreamToken(callback: (token: StreamToken) => void): () => void;

  // Filesystem (limité, sécurisé)
  readWorkspaceFile(relativePath: string): Promise<string>;
  listWorkspaceFiles(): Promise<string[]>;

  // Persistence sessions (localStorage Electron, pas navigateur)
  saveSessions(sessions: Session[]): Promise<void>;
  loadSessions(): Promise<Session[]>;
}
```

### 3.3 MCP Bridge (main process) — mcp-bridge.ts

Le bridge gère le subprocess Python McpServer :

```typescript
class McpBridge {
  private proc: ChildProcess | null = null;
  private requestId = 0;
  private pending = new Map<number, PendingRequest>();

  // Démarrage du serveur Python
  async start(): Promise<void>
  // Envoi d'une requête JSON-RPC
  async call(method: string, params: object): Promise<unknown>
  // Arrêt propre (SIGTERM + timeout 3s + SIGKILL)
  async stop(): Promise<void>
  // Reconnexion automatique sur crash (max 3 tentatives, backoff 1s/2s/5s)
  private onCrash(): void
}
```

**Commande subprocess** :
```
sys.executable D:\LLMCodeAgent\core\mcp_server.py
```
(Jamais `"python"` hardcodé — conforme Règle 8 LCCA)

**Flux stdout ligne par ligne** :
- Chaque ligne reçue = un objet JSON-RPC → `JSON.parse` → dispatch vers `pending.get(id)`
- Ligne non-JSON → log interne (messages de démarrage McpServer)

### 3.4 Streaming des réponses

McpServer ne streame pas nativement (JSON-RPC stdio synchrone). Le streaming de
l'interface est **simulé côté renderer** en affichant les tokens progressivement
après réception complète, avec un délai configurable (défaut : 15ms/token).

Pour un vrai streaming LLM en V2 : ajouter un channel dédié dans le bridge
(événements `stream_token` via IPC) en parallèle des réponses JSON-RPC.

---

## 4. State Management — Stores Zustand

### 4.1 chatStore.ts

```typescript
interface ChatState {
  sessions: Session[];
  activeSessionId: string | null;

  // Messages de la session active
  messages: Message[];

  // Streaming
  isStreaming: boolean;
  streamBuffer: string;

  // Actions
  createSession(): string;
  setActiveSession(id: string): void;
  appendMessage(msg: Message): void;
  appendStreamToken(token: string): void;
  finalizeStream(): void;
  clearActiveSession(): void;
  deleteSession(id: string): void;
}

interface Session {
  id: string;         // uuid v4
  title: string;      // auto-généré depuis le 1er message
  createdAt: string;  // ISO-8601
  updatedAt: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;      // Markdown brut
  createdAt: string;
  txBadge?: TxBadge;    // Présent si la réponse contient une TX
  specBadge?: SpecBadge; // Présent si une spec a été générée
}
```

### 4.2 contextStore.ts

```typescript
interface ContextState {
  // Workspace
  workspaceFiles: string[];       // chemins relatifs
  modifiedFiles: string[];        // fichiers de la dernière TX

  // Specs
  activeSpecs: SpecSummary[];     // 5 dernières specs lcca_specs
  selectedSpec: SpecEntry | null; // spec affichée en détail

  // Transactions
  recentTx: TxRecord[];           // 10 dernières TX

  // MCP Status
  mcpStatus: McpStatus;
  llmStatus: LlmStatus;

  // Actions
  refreshWorkspace(): Promise<void>;
  refreshSpecs(): Promise<void>;
  selectSpec(specId: string): Promise<void>;
  refreshTransactions(): Promise<void>;
  setMcpStatus(status: McpStatus): void;
}

type McpStatus = 'connecting' | 'connected' | 'disconnected' | 'error';
type LlmStatus = 'active' | 'stub' | 'unknown';

interface TxRecord {
  txId: string;
  files: string[];
  status: 'committed' | 'rolled_back' | 'partial';
  timestamp: string;
}

interface SpecSummary {
  specId: string;
  title: string;
  domain: string;
  validated: boolean;
  createdAt: string;
}
```

### 4.3 settingsStore.ts

```typescript
interface SettingsState {
  theme: 'dark' | 'light';
  panelMode: 'standard' | 'compact' | 'focus';
  fontSize: 'sm' | 'md' | 'lg';   // multiplicateur sur --font-size-base
  streamingDelay: number;          // ms/token (défaut 15)
  autoStartServer: boolean;        // démarrer McpServer au lancement (défaut true)
  workspacePath: string;           // D:\LLMCodeAgent (persisté)
  pythonPath: string;              // chemin sys.executable (auto-détecté)

  // Actions
  setTheme(theme: 'dark' | 'light'): void;
  setPanelMode(mode: PanelMode): void;
  persist(): void;   // sauvegarde dans electron-store
  load(): void;
}
```

---

## 5. Intégration MCP — Tool calls

### 5.1 Hook useMcp.ts

```typescript
function useMcp() {
  const call = async <T>(tool: string, args: Record<string, unknown>): Promise<T> => {
    const result = await window.lcca.mcpCall(tool, args);
    if (result.error) throw new McpError(result.error.code, result.error.message);
    return JSON.parse(result.content[0].text) as T;
  };

  return {
    generateSpec: (intent: string, domain: string) =>
      call<GenerateSpecResult>('generate_spec', { intent, domain }),

    validateSpec: (specId?: string, bodyMd?: string) =>
      call<ValidateSpecResult>('validate_spec', { spec_id: specId, body_md: bodyMd }),

    memorySearch: (query: string, n = 5) =>
      call<MemorySearchResult>('memory_search', { query, n }),

    editBatch: (files: EditBatchFile[]) =>
      call<EditBatchResult>('edit_batch', { files }),

    sandboxRun: (code: string) =>
      call<SandboxResult>('sandbox_run', { code }),

    evaluateQuality: (code: string) =>
      call<EvalResult>('evaluate_quality', { code }),
  };
}
```

### 5.2 Traitement des réponses TX

Quand une réponse assistant contient une transaction (détection par pattern dans le
texte retourné), le renderer extrait les métadonnées et génère un `TxBadge` :

```typescript
function extractTxBadge(responseText: string): TxBadge | null {
  // Pattern : "TX: tx_xxxxxxxx | Fichiers: x, y | Statut: ✅ Commité"
  const match = responseText.match(/TX:\s*(tx_\w+)\s*\|\s*Fichiers:\s*([^|]+)\|.*?(✅|↩|⚠)/);
  if (!match) return null;
  return {
    txId: match[1],
    files: match[2].split(',').map(f => f.trim()),
    status: match[3] === '✅' ? 'committed' : match[3] === '↩' ? 'rolled_back' : 'partial',
  };
}
```

---

## 6. Persistence des sessions

Les sessions de chat sont sauvegardées dans le dossier userData Electron :

```
%APPDATA%\LCCADesktop\sessions\
├── index.json          # { sessions: Session[] } (titres + ids)
└── {session-id}.json   # { messages: Message[] }
```

Limite : 50 sessions max, messages par session : 500 max.
Au-delà : archivage automatique dans `sessions/archive/`.

---

## 7. Build & packaging

### 7.1 Dev

```powershell
cd D:\LLMCodeAgent\ui
npm install
npm run dev          # electron-vite + hot-reload
```

### 7.2 Production

```powershell
npm run build        # Compile TypeScript + bundle Vite
npm run dist         # electron-builder → D:\LLMCodeAgent\ui\dist\
```

**Output** : installeur NSIS Windows `LCCA-Desktop-Setup-1.0.0.exe`

### 7.3 electron-builder.yml (extrait)

```yaml
appId: com.lcca.desktop
productName: LCCA Desktop
directories:
  output: dist
win:
  target: nsis
  icon: assets/icon.ico
nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
extraResources:
  # Inclure le venv Python dans le package (optionnel V1)
  # - from: ../../venv
  #   to: venv
```

---

## 8. Sécurité

| Menace | Mitigation |
|--------|-----------|
| XSS dans Markdown | `rehype-sanitize` sur tout contenu externe ; `dangerouslySetInnerHTML` interdit |
| Path traversal depuis UI | `safe_path()` appelé côté Python + validation côté preload |
| Injection commandes subprocess | Spawn avec argv array (jamais shell string) |
| Accès filesystem illimité | `contextBridge` expose uniquement `readWorkspaceFile` avec whitelist |
| Session hijacking | Pas de réseau → risque nul ; sessions stockées localement |

<!-- AI-READY | Spec UI-02 Architecture Technique | Version 1.0.0 | 2026-04-18 -->
