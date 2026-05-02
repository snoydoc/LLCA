# Spec UI-03 — Composants & Comportements
<!-- AI-READY | Composants LCCA Desktop | Version 1.0.0 | 2026-04-18 -->

## 1. Arbre des composants

```
App
├── TitleBar
├── CommandPalette           (modal, Ctrl+K)
├── Layout
│   ├── Sidebar
│   │   ├── SidebarNav       (icônes sessions, settings)
│   │   └── SessionList      (mode étendu)
│   ├── ChatPanel
│   │   ├── MessageList
│   │   │   ├── MessageBubble (user | assistant)
│   │   │   │   ├── MarkdownRenderer
│   │   │   │   ├── CodeBlock        (avec bouton Copy)
│   │   │   │   ├── TxBadge          (si TX détectée)
│   │   │   │   └── SpecBadge        (si spec générée)
│   │   │   └── StreamingIndicator   (points pulsants)
│   │   └── InputZone
│   │       ├── TextArea
│   │       ├── ActionBar            (boutons Spec/Fichier/DSL)
│   │       └── SendButton
│   └── ContextPanel
│       ├── McpStatusBar
│       ├── WorkspaceSection
│       │   └── FileTree
│       ├── SpecsSection
│       │   ├── SpecCard             (résumé)
│       │   └── SpecDetailModal      (body_md rendu)
│       └── TxSection
│           └── TxCard
└── SettingsModal
```

---

## 2. TitleBar

### Apparence
```
┌──────────────────────────────────────────────────────────────────────┐
│  ⬡ LCCA Desktop   v7.2   [● Connecté]  [🤖 Ollama]     [🌙] [⚙] [-][□][×]│
└──────────────────────────────────────────────────────────────────────┘
```

### Props
```typescript
interface TitleBarProps {} // Lit depuis contextStore
```

### Comportements
- Zone draggable : `-webkit-app-region: drag` sur toute la barre SAUF les boutons
- Indicateur MCP : couleur dynamique depuis `contextStore.mcpStatus`
- Indicateur Ollama : affiché seulement si status connu
- Bouton 🌙 : toggle thème (appelle `settingsStore.setTheme`)
- Bouton ⚙ : ouvre `SettingsModal`
- Boutons `-` `□` `×` : `ipcRenderer.send('window-control', action)`

---

## 3. Sidebar

### Mode icônes (compact, 52px)
```
┌────┐
│ 💬 │  ← Sessions (actif si chat panel)
│ ⚙  │  ← Settings
│    │
│ ?  │  ← Aide (ouvre doc)
└────┘
```

### Mode étendu (200px, `Ctrl+B`)
```
┌────────────────────┐
│ 💬 Sessions        │
│ ─────────────────  │
│ ● Session actuelle │ ← badge bleu
│   Ma session 1     │
│   Ma session 2     │
│ ─────────────────  │
│ ⚙ Settings        │
└────────────────────┘
```

### SessionList item
- Titre : 20 chars max + ellipsis
- Sous-titre : date relative ("il y a 2h", "hier")
- Actions au hover : `[✏]` rename / `[🗑]` supprimer
- Clic : charge la session dans ChatPanel

---

## 4. ChatPanel

### 4.1 MessageList

Scrollable (`overflow-y: auto`), scroll automatique vers le bas à chaque nouveau
message, sauf si l'utilisateur a scrollé manuellement vers le haut (détecter via
`scrollTop + clientHeight < scrollHeight - 50px`).

**Groupement visuel** :
- Messages consécutifs du même rôle dans les 60 secondes → groupés (pas de re-affichage
  de l'avatar, padding réduit entre eux)

**Vide state** :
```
┌──────────────────────────────────┐
│           ⬡                     │
│     LCCA Desktop v7.2            │
│                                  │
│   Tapez une commande DSL         │
│   ou décrivez une tâche          │
│                                  │
│  [📋 Générer une spec]           │
│  [📁 Explorer le workspace]      │
└──────────────────────────────────┘
```

### 4.2 MessageBubble

```typescript
interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}
```

**User bubble** :
- Aligné à droite
- `background: var(--accent-soft)`
- Padding : `var(--space-sm) var(--space-md)`
- Border-radius : `var(--radius-lg) var(--radius-lg) var(--radius-sm) var(--radius-lg)`
- Pas de Markdown (texte brut)

**Assistant bubble** :
- Aligné à gauche, avec avatar `⬡` (hexagone LCCA)
- `background: var(--bg-surface)`
- Contenu : `<MarkdownRenderer>` (Markdown complet)
- Border-radius : `var(--radius-lg) var(--radius-lg) var(--radius-lg) var(--radius-sm)`

### 4.3 MarkdownRenderer

Utilise `react-markdown` + `rehype-highlight` + `rehype-sanitize`.

**Éléments supportés** :
- Titres H1-H4 (H1 redimensionné à H3 dans les bulles)
- Paragraphes, listes ul/ol, tableaux
- `code` inline (fond `--code-bg`, police mono)
- Blocs code avec détection langage + coloration
- Blockquote → style info-box
- `---` → séparateur fin

**`CodeBlock` (composant dédié)** :
```typescript
interface CodeBlockProps {
  language: string;    // 'python', 'typescript', 'json', ''
  code: string;
  filename?: string;   // si présent, affiché en header
}
```
Features :
- Header : `[python]` + `[📋 Copier]` + `[filename si présent]`
- `[📋 Copier]` : copie dans clipboard, bascule sur `[✓ Copié]` 2 secondes
- Numéros de lignes si > 5 lignes
- Scroll horizontal si ligne trop longue (pas de wrap)
- Theme highlight.js : `github-dark` / `github` selon thème actif

### 4.4 TxBadge

Affiché sous une bulle assistant quand une transaction est détectée.

```typescript
interface TxBadgeProps {
  txId: string;
  files: string[];
  status: 'committed' | 'rolled_back' | 'partial';
  onRollback?: () => void;  // si status === 'committed'
}
```

**Apparence** :
```
┌──────────────────────────────────────────────┐
│  ✅ tx_a3b4c5d6  │  core/spec_entry.py +2   │
│  [↩ Annuler]     │  il y a 3s               │
└──────────────────────────────────────────────┘
```

- `committed` → badge vert, bouton `[↩ Annuler]` visible 30 secondes puis masqué
- `rolled_back` → badge orange, texte "Annulée"
- `partial` → badge jaune, texte "Partielle ⚠"

**`[↩ Annuler]`** : déclenche `mcp.editBatch` avec rollback, confirmation dialog d'abord :
```
Annuler la transaction tx_a3b4c5d6 ?
Les fichiers modifiés seront restaurés.
[Annuler] [Confirmer ↩]
```

### 4.5 SpecBadge

Affiché quand `generate_spec` a été appelé par l'assistant.

```typescript
interface SpecBadgeProps {
  specId: string;
  title: string;
  domain: string;
  validated: boolean;
  score: number;
  onView: () => void;    // ouvre SpecDetailModal
  onExport: () => void;  // export .md
}
```

**Apparence** :
```
┌──────────────────────────────────────────────┐
│  📋 Spec générée : "Refactor TransactionMgr" │
│  mcp · score 0.92 · ✅ Validée              │
│  [Voir] [Exporter .md]                       │
└──────────────────────────────────────────────┘
```

Couleur du badge score :
- score ≥ 0.8 → `--success`
- 0.5 ≤ score < 0.8 → `--warning`
- score < 0.5 → `--error`

### 4.6 StreamingIndicator

Affiché dans la MessageList pendant qu'une réponse est en cours :
```
⬡  ·  ·  ·        ← 3 points pulsants (animation CSS, 600ms décalés)
```
Disparaît quand `isStreaming` passe à false.

### 4.7 InputZone

```typescript
interface InputZoneProps {
  onSend: (text: string) => void;
  disabled: boolean;  // true pendant streaming
}
```

**TextArea** :
- `min-height: 52px`, `max-height: 200px` (auto-resize)
- `resize: none`
- Police : `var(--font-mono)` (commandes DSL lisibles)
- Placeholder adaptatif selon mode MCP :
  - Connecté : "Tapez une commande DSL ou décrivez une tâche…"
  - Déconnecté : "McpServer déconnecté — démarrage en cours…"
  - Streaming : "" (disabled)

**Historique des commandes** :
- Stocké dans `chatStore` (50 dernières)
- Navigation `↑`/`↓` dans le TextArea quand curseur en ligne 1/dernière ligne

**ActionBar** (boutons sous le TextArea) :
```
[📋 Spec]  [📁 Fichier]  [⚡ DSL]  [⚙ Modèle: stub]
```
- `[📋 Spec]` : préfixe le texte avec `@spec `
- `[📁 Fichier]` : ouvre file picker → insert `@file core/spec_entry.py` dans le TextArea
- `[⚡ DSL]` : bascule mode DSL (coloration spéciale dans le TextArea)
- `[⚙ Modèle]` : badge statut Ollama (clic → refresh status)

**SendButton** :
- Icône `→` normal, spinner pendant streaming
- `background: var(--accent)`
- Désactivé si TextArea vide ou streaming

---

## 5. ContextPanel

Panel droit (280px), masquable via `Ctrl+\`.

### 5.1 McpStatusBar

```
● Connecté — McpServer V7.2    [⟳ Redémarrer]
🤖 Ollama actif — qwen2.5-coder:14b
```
- Couleurs dynamiques selon `contextStore.mcpStatus`
- `[⟳ Redémarrer]` : `window.lcca.restartServer()` + confirmation si session active

### 5.2 WorkspaceSection

```
📁 Workspace                          [⟳]
─────────────────────────────────────
core/
  ├ spec_entry.py        [✏ modifié]
  ├ mcp_server.py
  └ orchestrator.py
tests/
  └ test_spec_layer.py
```

- `FileTree` : arbre collapsible, profondeur max 3
- Fichiers modifiés (depuis `contextStore.modifiedFiles`) → badge `[✏]` orange
- Clic sur un fichier → `window.lcca.readWorkspaceFile(path)` + affiche dans une modal
- `[⟳]` → `contextStore.refreshWorkspace()`

### 5.3 SpecsSection

```
📋 Specs actives (3)                  [⟳]
─────────────────────────────────────
[✅] Refactor TransactionMgr   mcp
[✅] Spec Layer Core           spec
[⚠] Draft orchestration      global
```

**SpecCard** :
- Titre tronqué (24 chars)
- Domain + badge validated/invalide
- Clic → ouvre `SpecDetailModal`

**SpecDetailModal** :
```
┌──────────────────────────────────────────────────┐
│  📋 Refactor TransactionManager          [×]    │
│  ID: a3b4c5d6e7f8 · mcp · v7.2.0 · score 0.92  │
│  ──────────────────────────────────────────────  │
│  [body_md rendu en Markdown complet]             │
│                                                  │
│  Violations (0)                                  │
│  ──────────────────────────────────────────────  │
│                    [Exporter .md]  [Fermer]      │
└──────────────────────────────────────────────────┘
```

Si violations > 0 :
```
Violations (2)
[BLOCKING] rule_3_max_files — fix: limiter à 3 fichiers
[WARNING]  rule_10_utf8_sig — fix: JSON en utf-8 sans BOM
```

### 5.4 TxSection

```
🔄 Transactions récentes              [⟳]
─────────────────────────────────────
✅ tx_a3b4c5d6  core/spec_entry.py   2min
✅ tx_11223344  tests/test_spec_la…  1h
↩ tx_55667788  core/orchestrator…  hier
```

**TxCard** :
- Status icon + txId (8 chars) + 1er fichier modifié + temps relatif
- Hover : affiche tous les fichiers modifiés
- Clic : affiche détail TX dans une modal (WAL entries)

---

## 6. CommandPalette (Ctrl+K)

Modal centrée, fuzzy search sur toutes les actions disponibles.

```
┌──────────────────────────────────────────────────┐
│  🔍 Rechercher une action...                    │
│  ──────────────────────────────────────────────  │
│  💬 Nouvelle session                 Ctrl+N     │
│  📋 Générer une spec...                         │
│  🔄 Relancer McpServer                          │
│  ⚙  Ouvrir settings                 Ctrl+,     │
│  🌙 Basculer thème                  Ctrl+⇧T    │
│  📁 Explorer workspace                          │
│  [résultats filtrés dynamiquement]               │
└──────────────────────────────────────────────────┘
```

- Fermeture : `Escape` ou clic outside
- Navigation : `↑`/`↓`, sélection : `Enter`
- Source des actions : liste statique + sessions récentes + specs récentes

---

## 7. SettingsModal

```
┌──────────────────────────────────────────────────┐
│  ⚙ Paramètres                           [×]    │
│  ──────────────────────────────────────────────  │
│  Apparence                                       │
│    Thème        ○ Sombre  ● Clair               │
│    Taille texte ○ Petit  ● Normal  ○ Grand      │
│                                                  │
│  Performances                                    │
│    Délai streaming     [15] ms/token             │
│                                                  │
│  Serveur                                         │
│    Workspace           [D:\LLMCodeAgent    ] [📁]│
│    Python              [Auto-détecté       ]     │
│    Démarrage auto      [✓]                      │
│                                                  │
│  À propos                                        │
│    LCCA Desktop v1.0.0 · McpServer V7.2          │
│                        [Fermer]                  │
└──────────────────────────────────────────────────┘
```

Tous les changements sont appliqués en temps réel + persistés via `settingsStore.persist()`.

---

## 8. Animations & transitions

| Élément | Animation | Durée |
|---------|-----------|-------|
| Apparition bulle message | `fadeInUp` (translateY 8px → 0) | 150ms ease-out |
| TxBadge | `slideIn` depuis le bas | 200ms ease-out |
| Panel context toggle | `width` 280px → 0 | 250ms ease-in-out |
| Modal overlay | `opacity` 0 → 0.5 | 150ms |
| Modal content | `scale` 0.95 → 1 | 150ms ease-out |
| StreamingIndicator dots | `opacity` pulse décalé | 600ms infinite |
| Status indicator | `box-shadow` pulse | 2000ms infinite (si connecting) |

**Règle** : `prefers-reduced-motion: reduce` → toutes les animations désactivées.

---

## 9. Gestion des erreurs — UX

### Erreur MCP (code -32xxx)
Affichée inline dans le chat comme bulle système :
```
⚠ Erreur MCP [-32602] : 'intent' est requis
```
Couleur : `--error`, fond `--bg-surface`.

### Timeout LLM (> 30s sans réponse)
```
⏱ La génération prend plus de temps que prévu…
[Annuler]
```
`[Annuler]` : envoie une commande d'interruption au bridge, vide le streamBuffer.

### Serveur déconnecté pendant une session
Banner persistant en haut du ChatPanel :
```
⚠  McpServer déconnecté — Reconnexion automatique dans 3s…  [Relancer maintenant]
```
Disparaît quand `mcpStatus` repasse à `connected`.

### Erreur fatale (crash Electron)
Fichier de crash log dans `%APPDATA%\LCCADesktop\logs\crash-{date}.log`
Dialog natif Electron : "LCCA Desktop a rencontré une erreur. Voir le log."

---

## 10. Types TypeScript complets — mcp.ts

```typescript
// Résultat d'un tool MCP (enveloppé par le bridge)
interface McpResult {
  content?: Array<{ type: 'text'; text: string }>;
  error?: { code: number; message: string; data?: unknown };
  isError?: boolean;
}

// generate_spec result
interface GenerateSpecResult {
  spec_id: string;
  domain: string;
  version: string;
  title: string;
  abstract: string;
  complexity_score: number;
  validated: boolean;
  score: number;
  violations: ViolationEntry[];
  validation_notes: string;
}

// validate_spec result
interface ValidateSpecResult {
  spec_id: string;
  valid: boolean;
  score: number;
  blocking: number;
  violations: ViolationEntry[];
  validation_notes: string;
}

interface ViolationEntry {
  rule: string;
  severity: 'blocking' | 'warning';
  location: string;
  fix_suggestion: string;
}

// memory_search result
interface MemorySearchResult {
  solutions: MemoryEntry[];
  failures: MemoryEntry[];
  context: MemoryEntry[];
  specs: MemoryEntry[];
}

interface MemoryEntry {
  id: string;
  content: string;
  metadata: Record<string, unknown>;
  distance: number;
}

// edit_batch result
interface EditBatchResult {
  success: boolean;
  applied: number;
  errors: string[];
  tx_id?: string;
}

// sandbox_run result
interface SandboxResult {
  success: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
}

// McpStatus (depuis le bridge)
interface McpStatus {
  status: 'connecting' | 'connected' | 'disconnected' | 'error';
  serverVersion?: string;
  uptime?: number;   // secondes
  lastError?: string;
}

// Event envoyé par le main process
type McpEvent =
  | { type: 'status_change'; payload: McpStatus }
  | { type: 'stream_token'; payload: StreamToken }
  | { type: 'tx_completed'; payload: TxRecord };

interface StreamToken {
  sessionId: string;
  messageId: string;
  token: string;
  done: boolean;
}
```

<!-- AI-READY | Spec UI-03 Composants & Comportements | Version 1.0.0 | 2026-04-18 -->
