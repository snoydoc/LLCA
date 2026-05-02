# Sprint UI-02 — Historique sessions + Markdown + TxBadge + SpecBadge
<!-- AI-READY | Sprint UI-02 | Version 1.0.0 | 2026-04-18 -->

## Contexte & objectif

Sprint UI-01 a livré un chat fonctionnel mais brut. Ce sprint le rend professionnel :
rendu Markdown complet avec coloration syntaxique, badges de transaction et de spec,
gestion des sessions avec persistance, et streaming simulé optimisé.

**Prérequis** : Sprint UI-01 vert (`npm run dev` fonctionnel, MCP connecté).
**Livrable** : Les réponses s'affichent en Markdown formaté. Les TX et specs générées
apparaissent comme badges interactifs. Les sessions sont persistées entre redémarrages.

---

## Périmètre

| # | Fichier | Type | Description |
|---|---------|------|-------------|
| 1 | `src/components/MarkdownRenderer.tsx` | CREATE | react-markdown + rehype-highlight + sanitize |
| 2 | `src/components/CodeBlock.tsx` | CREATE | Bloc code avec header + copy button |
| 3 | `src/components/TxBadge.tsx` | CREATE | Badge transaction avec rollback |
| 4 | `src/components/SpecBadge.tsx` | CREATE | Badge spec avec score + actions |
| 5 | `src/components/StreamingIndicator.tsx` | CREATE | 3 points pulsants |
| 6 | `src/components/MessageBubble.tsx` | UPDATE | Intégrer MarkdownRenderer + badges |
| 7 | `src/components/Sidebar.tsx` | UPDATE | SessionList fonctionnelle |
| 8 | `src/hooks/useStreaming.ts` | CREATE | Hook streaming simulé |
| 9 | `src/hooks/useShortcuts.ts` | CREATE | Raccourcis clavier globaux |
| 10 | `src/stores/chatStore.ts` | UPDATE | Persistence sessions JSON |
| 11 | `src/utils/extractors.ts` | CREATE | extractTxBadge + extractSpecBadge |
| 12 | `electron/main.ts` | UPDATE | IPC sessions save/load (userData) |

---

## Tâche 1 — MarkdownRenderer

### `src/components/MarkdownRenderer.tsx`

```tsx
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import rehypeSanitize from 'rehype-sanitize';
import { CodeBlock } from './CodeBlock';

interface Props {
  content: string;
  isStreaming?: boolean;
}

export function MarkdownRenderer({ content, isStreaming }: Props) {
  return (
    <ReactMarkdown
      rehypePlugins={[rehypeSanitize, rehypeHighlight]}
      components={{
        // Redimensionner H1 → H3 dans les bulles
        h1: ({ children }) => <h3 className="md-h1">{children}</h3>,
        h2: ({ children }) => <h4 className="md-h2">{children}</h4>,
        // CodeBlock dédié pour les blocs fenced
        code({ node, inline, className, children }) {
          const lang = /language-(\w+)/.exec(className ?? '')?.[1] ?? '';
          if (inline) return <code className="inline-code">{children}</code>;
          return <CodeBlock language={lang} code={String(children).trimEnd()} />;
        },
        // Blockquote → info-box
        blockquote: ({ children }) => (
          <div className="blockquote-info">{children}</div>
        ),
        // Tables avec wrapper scrollable
        table: ({ children }) => (
          <div className="table-wrapper"><table>{children}</table></div>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
```

**CSS associé** (dans `globals.css`) :
```css
.inline-code   { background: var(--code-bg); font-family: var(--font-mono);
                 font-size: var(--font-size-sm); padding: 1px 5px;
                 border-radius: var(--radius-sm); }
.blockquote-info { border-left: 3px solid var(--accent); padding: var(--space-sm) var(--space-md);
                   background: var(--bg-surface); margin: var(--space-sm) 0;
                   border-radius: 0 var(--radius-md) var(--radius-md) 0; }
.table-wrapper { overflow-x: auto; margin: var(--space-sm) 0; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: var(--space-xs) var(--space-sm); border: 1px solid var(--border);
         font-size: var(--font-size-sm); }
th { background: var(--bg-surface); }
.md-h1 { font-size: var(--font-size-lg); margin: var(--space-md) 0 var(--space-sm); }
.md-h2 { font-size: var(--font-size-md); margin: var(--space-sm) 0; }
```

---

## Tâche 2 — CodeBlock

### `src/components/CodeBlock.tsx`

Spec complète : `spec-ui-03-composants.md` section 4.3.

```tsx
import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

interface CodeBlockProps {
  language: string;
  code: string;
  filename?: string;
}

export function CodeBlock({ language, code, filename }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const lineCount = code.split('\n').length;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-block-lang">{language || 'text'}</span>
        {filename && <span className="code-block-filename">{filename}</span>}
        <button className="code-block-copy" onClick={handleCopy} aria-label="Copier le code">
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? 'Copié' : 'Copier'}
        </button>
      </div>
      <pre className={`code-block-pre ${lineCount > 5 ? 'with-line-numbers' : ''}`}>
        <code>{code}</code>
      </pre>
    </div>
  );
}
```

**CSS** :
```css
.code-block { border-radius: var(--radius-md); overflow: hidden;
              margin: var(--space-sm) 0; border: 1px solid var(--border); }
.code-block-header { display: flex; align-items: center; gap: var(--space-sm);
                     background: var(--code-bg); padding: var(--space-xs) var(--space-sm);
                     border-bottom: 1px solid var(--border); }
.code-block-lang { font-family: var(--font-mono); font-size: var(--font-size-xs);
                   color: var(--accent); text-transform: lowercase; }
.code-block-filename { font-size: var(--font-size-xs); color: var(--text-muted);
                       margin-left: auto; }
.code-block-copy { display: flex; align-items: center; gap: 4px; margin-left: auto;
                   background: transparent; border: none; color: var(--text-secondary);
                   font-size: var(--font-size-xs); cursor: pointer; padding: 2px 6px;
                   border-radius: var(--radius-sm); }
.code-block-copy:hover { background: var(--bg-surface); color: var(--text-primary); }
.code-block-pre { background: var(--code-bg); padding: var(--space-sm) var(--space-md);
                  overflow-x: auto; font-family: var(--font-mono);
                  font-size: var(--font-size-sm); line-height: var(--line-height-code);
                  white-space: pre; }
```

---

## Tâche 3 — TxBadge

### `src/components/TxBadge.tsx`

Spec : `spec-ui-03-composants.md` section 4.4.

```tsx
import { useState, useEffect } from 'react';
import { CheckCircle, RotateCcw, AlertTriangle } from 'lucide-react';
import type { TxBadge as TxBadgeType } from '../types/chat';

interface Props {
  badge: TxBadgeType;
  onRollback?: (txId: string) => Promise<void>;
}

export function TxBadge({ badge, onRollback }: Props) {
  // Bouton rollback masqué après 30 secondes
  const [showRollback, setShowRollback] = useState(badge.status === 'committed');
  const [confirming, setConfirming] = useState(false);
  const [rolling, setRolling] = useState(false);

  useEffect(() => {
    if (badge.status !== 'committed') return;
    const t = setTimeout(() => setShowRollback(false), 30_000);
    return () => clearTimeout(t);
  }, [badge.status]);

  const statusIcon = badge.status === 'committed'   ? <CheckCircle size={14} />
                   : badge.status === 'rolled_back' ? <RotateCcw size={14} />
                   :                                  <AlertTriangle size={14} />;

  const statusColor = badge.status === 'committed'   ? 'var(--success)'
                    : badge.status === 'rolled_back' ? 'var(--warning)'
                    :                                  'var(--error)';

  const handleRollback = async () => {
    if (!confirming) { setConfirming(true); return; }
    setRolling(true);
    await onRollback?.(badge.txId);
    setRolling(false);
    setConfirming(false);
    setShowRollback(false);
  };

  const filesDisplay = badge.files.slice(0, 2).join(', ')
    + (badge.files.length > 2 ? ` +${badge.files.length - 2}` : '');

  return (
    <div className="tx-badge" style={{ borderColor: statusColor }}>
      <span className="tx-badge-icon" style={{ color: statusColor }}>{statusIcon}</span>
      <span className="tx-badge-id">{badge.txId.slice(0, 8)}</span>
      <span className="tx-badge-files">{filesDisplay}</span>
      {showRollback && onRollback && (
        <button className="tx-badge-rollback" onClick={handleRollback} disabled={rolling}>
          {confirming ? 'Confirmer ↩' : '↩ Annuler'}
        </button>
      )}
    </div>
  );
}
```

---

## Tâche 4 — SpecBadge

### `src/components/SpecBadge.tsx`

Spec : `spec-ui-03-composants.md` section 4.5.

```tsx
import { FileText, ExternalLink, Download } from 'lucide-react';
import type { SpecBadge as SpecBadgeType } from '../types/chat';

interface Props {
  badge: SpecBadgeType;
  onView:   () => void;
  onExport: () => void;
}

export function SpecBadge({ badge, onView, onExport }: Props) {
  const scoreColor = badge.score >= 0.8 ? 'var(--success)'
                   : badge.score >= 0.5 ? 'var(--warning)'
                   :                      'var(--error)';

  return (
    <div className="spec-badge">
      <FileText size={14} className="spec-badge-icon" />
      <div className="spec-badge-info">
        <span className="spec-badge-title">📋 {badge.title}</span>
        <span className="spec-badge-meta">
          {badge.domain}
          <span style={{ color: scoreColor }}> · score {badge.score.toFixed(2)}</span>
          {badge.validated && <span style={{ color: 'var(--success)' }}> · ✅ Validée</span>}
        </span>
      </div>
      <div className="spec-badge-actions">
        <button onClick={onView}   aria-label="Voir la spec"><ExternalLink size={13} /> Voir</button>
        <button onClick={onExport} aria-label="Exporter la spec"><Download size={13} /> .md</button>
      </div>
    </div>
  );
}
```

---

## Tâche 5 — StreamingIndicator

### `src/components/StreamingIndicator.tsx`

```tsx
export function StreamingIndicator() {
  return (
    <div className="streaming-indicator" aria-label="Réponse en cours">
      <span className="avatar-icon">⬡</span>
      <span className="dot dot-1" />
      <span className="dot dot-2" />
      <span className="dot dot-3" />
    </div>
  );
}
```

**CSS animations** :
```css
.streaming-indicator { display: flex; align-items: center; gap: var(--space-sm);
                        padding: var(--space-sm) var(--space-md); }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted);
       animation: dotPulse 1.2s infinite; }
.dot-1 { animation-delay: 0s; }
.dot-2 { animation-delay: 0.2s; }
.dot-3 { animation-delay: 0.4s; }
@keyframes dotPulse {
  0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
  40%           { opacity: 1;   transform: scale(1);   }
}
@media (prefers-reduced-motion: reduce) { .dot { animation: none; opacity: 0.5; } }
```

---

## Tâche 6 — MessageBubble (mise à jour)

### `src/components/MessageBubble.tsx` — remplacer le texte brut

```tsx
import { MarkdownRenderer } from './MarkdownRenderer';
import { TxBadge } from './TxBadge';
import { SpecBadge } from './SpecBadge';
import { useContextStore } from '../stores/contextStore';
import type { Message } from '../types/chat';

interface Props {
  message: Message;
  isStreaming?: boolean;
  onSpecView?:   (specId: string) => void;
  onTxRollback?: (txId: string) => Promise<void>;
}

export function MessageBubble({ message, isStreaming, onSpecView, onTxRollback }: Props) {
  const isUser = message.role === 'user';

  return (
    <div className={`message-bubble ${isUser ? 'bubble-user' : 'bubble-assistant'}`}>
      {!isUser && <span className="bubble-avatar" aria-hidden>⬡</span>}
      <div className="bubble-content">
        {isUser
          ? <p>{message.content}</p>
          : <MarkdownRenderer content={message.content} isStreaming={isStreaming} />
        }
        {message.txBadge && (
          <TxBadge badge={message.txBadge} onRollback={onTxRollback} />
        )}
        {message.specBadge && (
          <SpecBadge
            badge={message.specBadge}
            onView={() => onSpecView?.(message.specBadge!.specId)}
            onExport={() => {/* UI-03 */}}
          />
        )}
      </div>
    </div>
  );
}
```

---

## Tâche 7 — Extracteurs (badges depuis le texte)

### `src/utils/extractors.ts`

```typescript
import type { TxBadge, SpecBadge } from '../types/chat';

// Détecte un pattern TX dans la réponse assistant
// Format attendu dans les réponses McpServer : "TX: tx_xxxx | Fichiers: a.py, b.py | ✅"
export function extractTxBadge(text: string): TxBadge | null {
  const m = text.match(/TX:\s*(tx_\w{1,20})\s*\|\s*Fichiers:\s*([^|]+?)\s*\|[^✅↩⚠]*(✅|↩|⚠)/);
  if (!m) return null;
  return {
    txId:      m[1],
    files:     m[2].split(',').map(f => f.trim()).filter(Boolean),
    status:    m[3] === '✅' ? 'committed' : m[3] === '↩' ? 'rolled_back' : 'partial',
    timestamp: new Date().toISOString(),
  };
}

// Détecte un pattern SpecBadge dans la réponse
// Format : "SPEC_GENERATED: specId=xxx title=yyy domain=zzz validated=true score=0.92"
export function extractSpecBadge(text: string): SpecBadge | null {
  const m = text.match(/SPEC_GENERATED:\s*specId=(\w+)\s+title=([^\n]+?)\s+domain=(\w+)\s+validated=(true|false)\s+score=([\d.]+)/);
  if (!m) return null;
  return {
    specId:    m[1],
    title:     m[2],
    domain:    m[3],
    validated: m[4] === 'true',
    score:     parseFloat(m[5]),
  };
}
```

---

## Tâche 8 — Persistence sessions

### IPC main process (ajout dans `electron/main.ts`)

```typescript
import { app } from 'electron';
import { join } from 'path';
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'fs';

const sessionsDir = join(app.getPath('userData'), 'sessions');
mkdirSync(sessionsDir, { recursive: true });

ipcMain.handle('sessions:save', (_event, sessions: unknown[]) => {
  writeFileSync(join(sessionsDir, 'index.json'), JSON.stringify({ sessions }), 'utf-8');
});

ipcMain.handle('sessions:load', () => {
  const p = join(sessionsDir, 'index.json');
  if (!existsSync(p)) return { sessions: [] };
  return JSON.parse(readFileSync(p, 'utf-8'));
});

ipcMain.handle('session:saveMessages', (_event, sessionId: string, messages: unknown[]) => {
  writeFileSync(join(sessionsDir, `${sessionId}.json`), JSON.stringify({ messages }), 'utf-8');
});

ipcMain.handle('session:loadMessages', (_event, sessionId: string) => {
  const p = join(sessionsDir, `${sessionId}.json`);
  if (!existsSync(p)) return { messages: [] };
  return JSON.parse(readFileSync(p, 'utf-8'));
});
```

### `chatStore.ts` (mise à jour)

Ajouter `persistSessions()` et `loadPersistedSessions()` qui appellent les IPC.
Appeler `persistSessions()` dans `appendMessage` et `createSession` (debounce 500ms).

### Sidebar SessionList (mise à jour)

```tsx
// SessionList affiche sessions depuis chatStore.sessions
// Titre auto-généré : 1ers 30 chars du 1er message user
// Clic → chatStore.setActiveSession(id)
// Actions hover : rename (inline edit) / supprimer (avec confirmation)
```

---

## Tâche 9 — Raccourcis clavier

### `src/hooks/useShortcuts.ts`

```typescript
import { useEffect } from 'react';

export function useShortcuts(handlers: Record<string, () => void>) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const ctrl = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();

      if (ctrl && key === 'n')             { e.preventDefault(); handlers['new-session']?.(); }
      if (ctrl && key === 'l')             { e.preventDefault(); handlers['clear-chat']?.(); }
      if (ctrl && key === '\\')            { e.preventDefault(); handlers['toggle-context']?.(); }
      if (ctrl && e.shiftKey && key === 'f') { e.preventDefault(); handlers['focus-mode']?.(); }
      if (ctrl && key === 'k')             { e.preventDefault(); handlers['command-palette']?.(); }
      if (ctrl && key === ',')             { e.preventDefault(); handlers['settings']?.(); }
      if (ctrl && e.shiftKey && key === 't') { e.preventDefault(); handlers['toggle-theme']?.(); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handlers]);
}
```

Appeler `useShortcuts` dans `App.tsx` avec les handlers correspondants.

---

## Critères d'acceptance Sprint UI-02

| Critère | Validation |
|---------|-----------|
| Réponse assistant en Markdown rendu (titres, listes, tableaux) | Manuel |
| Bloc code Python avec coloration syntaxique + bouton Copier | Manuel |
| Copier → bascule sur "✓ Copié" 2 secondes | Manuel |
| TxBadge visible si pattern TX détecté dans la réponse | Manuel |
| Bouton "↩ Annuler" masqué après 30s | Manuel |
| SpecBadge visible si pattern SPEC_GENERATED dans la réponse | Manuel |
| Score SpecBadge couleur correcte (vert/orange/rouge) | Manuel |
| StreamingIndicator pulsant pendant le streaming | Manuel |
| Sessions listées dans Sidebar | Manuel |
| Nouvelle session persistée après redémarrage Electron | Manuel |
| `Ctrl+N` crée et active une nouvelle session | Manuel |
| `Ctrl+\` toggle le ContextPanel | Manuel |
| `Ctrl+Shift+T` bascule thème dark/light | Manuel |

<!-- AI-READY | Sprint UI-02 Historique + Markdown + TxBadge + SpecBadge | Version 1.0.0 | 2026-04-18 -->
