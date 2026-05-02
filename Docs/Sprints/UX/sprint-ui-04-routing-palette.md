# Sprint UI-04 — CommandPalette + Routing MCP + Gestion erreurs
<!-- AI-READY | Sprint UI-04 | Version 1.0.0 | 2026-04-18 -->

## Contexte & objectif

Ce sprint apporte la maturité fonctionnelle. On résout le vrai problème de routing :
comment l'interface décide-t-elle d'appeler `generate_spec` plutôt que `memory_search`
selon ce que tape l'utilisateur ? On implémente la CommandPalette (Ctrl+K), on gère
les timeouts et erreurs de manière propre, et on expose toute la puissance des 9 tools
MCP depuis l'interface.

**Prérequis** : Sprint UI-03 vert.
**Livrable** : L'utilisateur peut piloter tous les tools MCP depuis le chat.
Les erreurs (timeout, déconnexion, erreur serveur) sont gérées proprement.
La CommandPalette permet d'accéder à toutes les actions en 2 frappes.

---

## Périmètre

| # | Fichier | Type | Description |
|---|---------|------|-------------|
| 1 | `src/components/CommandPalette.tsx` | CREATE | Palette Ctrl+K fuzzy search |
| 2 | `src/utils/router.ts` | CREATE | Routing intent → MCP tool |
| 3 | `src/utils/mcpFormatter.ts` | CREATE | Formatage réponses MCP → Markdown |
| 4 | `src/components/ChatPanel.tsx` | UPDATE | Routing réel + gestion timeout + erreurs |
| 5 | `src/components/ErrorBanner.tsx` | CREATE | Banner déconnexion + erreurs persistantes |
| 6 | `src/hooks/useMcp.ts` | UPDATE | Timeout hook + cancel |
| 7 | `src/stores/contextStore.ts` | UPDATE | Polling status MCP (3s) |

---

## Tâche 1 — Router intent → MCP tool

### `src/utils/router.ts`

Le router analyse le texte tapé et décide du tool MCP approprié. Logique heuristique
(pas de LLM pour le routing — le routing lui-même doit être instantané).

```typescript
export type RoutedIntent =
  | { tool: 'generate_spec';    args: { intent: string; domain: string } }
  | { tool: 'validate_spec';    args: { body_md: string } }
  | { tool: 'memory_search';    args: { query: string; n: number } }
  | { tool: 'project_search';   args: { query: string } }
  | { tool: 'sandbox_run';      args: { code: string } }
  | { tool: 'evaluate_quality'; args: { code: string } }
  | { tool: 'edit_batch';       args: { files: unknown[] } }
  | { tool: 'analyze_error';    args: Record<string, string> };

// Patterns de détection (ordre de priorité décroissante)
const PATTERNS: Array<{ test: (t: string) => boolean; route: (t: string) => RoutedIntent }> = [

  // @spec <intent> [domain:<domain>]
  { test: t => t.startsWith('@spec '),
    route: t => {
      const rest = t.slice(6).trim();
      const domainMatch = rest.match(/domain:(\w+)/);
      const domain = domainMatch?.[1] ?? inferDomain(rest);
      const intent = rest.replace(/domain:\w+/, '').trim();
      return { tool: 'generate_spec', args: { intent, domain } };
    }
  },

  // Bloc de code Python → sandbox ou evaluate
  { test: t => t.includes('```python') || t.startsWith('run:') || t.startsWith('exec:'),
    route: t => {
      const code = t.match(/```python\n?([\s\S]+?)```/)?.[1]
                ?? t.replace(/^(run:|exec:)\s*/i, '');
      return { tool: 'sandbox_run', args: { code } };
    }
  },

  // @eval ou "évalue ce code"
  { test: t => t.startsWith('@eval ') || /^évalue?\s+ce\s+code/i.test(t),
    route: t => {
      const code = t.replace(/^@eval\s+/i, '').trim();
      return { tool: 'evaluate_quality', args: { code } };
    }
  },

  // @file <path> ou "trouve le fichier"
  { test: t => t.startsWith('@file ') || /^(cherche?|trouve?|search)\s+/i.test(t),
    route: t => {
      const query = t.replace(/^(@file\s+|cherche?\s+|trouve?\s+|search\s+)/i, '').trim();
      return { tool: 'project_search', args: { query } };
    }
  },

  // "valide la spec" + body_md inline
  { test: t => /^valide?\s+(cette\s+)?spec/i.test(t),
    route: t => {
      const body = t.replace(/^valide?\s+(cette\s+)?spec[:.]?\s*/i, '');
      return { tool: 'validate_spec', args: { body_md: body } };
    }
  },

  // Fallback : memory_search (recherche sémantique généraliste)
  { test: () => true,
    route: t => ({ tool: 'memory_search', args: { query: t, n: 5 } })
  },
];

export function routeIntent(text: string): RoutedIntent {
  const trimmed = text.trim();
  for (const p of PATTERNS) {
    if (p.test(trimmed)) return p.route(trimmed);
  }
  return { tool: 'memory_search', args: { query: trimmed, n: 5 } };
}

// Inférence de domaine depuis le texte (heuristique)
export function inferDomain(text: string): string {
  const lower = text.toLowerCase();
  if (lower.includes('transaction') || lower.includes('rollback') || lower.includes('wal'))
    return 'transaction';
  if (lower.includes('ast') || lower.includes('libcst') || lower.includes('parse'))
    return 'ast';
  if (lower.includes('mcp') || lower.includes('json-rpc') || lower.includes('tool'))
    return 'mcp';
  if (lower.includes('sandbox') || lower.includes('docker') || lower.includes('subprocess'))
    return 'sandbox';
  if (lower.includes('memory') || lower.includes('chromadb') || lower.includes('vector'))
    return 'memory';
  if (lower.includes('spec') || lower.includes('validator') || lower.includes('rule'))
    return 'spec';
  if (lower.includes('orchestrat') || lower.includes('pipeline') || lower.includes('intent'))
    return 'orchestration';
  return 'global';
}
```

---

## Tâche 2 — MCP Formatter

### `src/utils/mcpFormatter.ts`

Transforme les résultats bruts des tools MCP en Markdown lisible pour les bulles assistant.

```typescript
import type { MemorySearchResult, GenerateSpecResult, ValidateSpecResult,
              SandboxResult, EditBatchResult } from '../types/mcp';

export function formatMcpResponse(tool: string, result: unknown): string {
  switch (tool) {
    case 'memory_search':   return formatMemorySearch(result as MemorySearchResult);
    case 'generate_spec':   return formatGenerateSpec(result as GenerateSpecResult);
    case 'validate_spec':   return formatValidateSpec(result as ValidateSpecResult);
    case 'sandbox_run':     return formatSandboxRun(result as SandboxResult);
    case 'evaluate_quality': return formatEvaluateQuality(result as Record<string, unknown>);
    case 'project_search':  return formatProjectSearch(result as Record<string, unknown>);
    case 'edit_batch':      return formatEditBatch(result as EditBatchResult);
    case 'analyze_error':   return formatAnalyzeError(result as Record<string, unknown>);
    default: return '```json\n' + JSON.stringify(result, null, 2) + '\n```';
  }
}

function formatMemorySearch(r: MemorySearchResult): string {
  const total = (r.solutions?.length ?? 0) + (r.specs?.length ?? 0)
              + (r.failures?.length ?? 0) + (r.context?.length ?? 0);
  if (total === 0) return '_Aucun résultat trouvé en mémoire pour cette requête._';

  const lines: string[] = [`**${total} résultat(s) trouvé(s)**\n`];

  if (r.specs?.length) {
    lines.push('### 📋 Specs');
    r.specs.forEach(e => lines.push(`- **${e.metadata?.title ?? e.id}** — ${e.metadata?.domain ?? ''}`));
  }
  if (r.solutions?.length) {
    lines.push('\n### ✅ Solutions');
    r.solutions.slice(0, 3).forEach(e => lines.push(`- ${e.content?.slice(0, 100)}…`));
  }
  if (r.failures?.length) {
    lines.push('\n### ❌ Échecs connus');
    r.failures.slice(0, 2).forEach(e => lines.push(`- ${e.content?.slice(0, 100)}…`));
  }
  return lines.join('\n');
}

function formatGenerateSpec(r: GenerateSpecResult): string {
  const status = r.validated ? '✅ Validée' : '⚠ Non validée';
  // Le pattern SPEC_GENERATED est détecté par extractors.ts pour créer le SpecBadge
  return [
    `**Spec générée** : ${r.title}`,
    ``,
    `| Champ | Valeur |`,
    `|-------|--------|`,
    `| Domain | \`${r.domain}\` |`,
    `| Version | ${r.version} |`,
    `| Complexité | ${r.complexity_score}/100 |`,
    `| Score | ${r.score.toFixed(2)} |`,
    `| Statut | ${status} |`,
    ``,
    r.violations.length > 0
      ? `**${r.violations.length} violation(s)** — voir le badge ci-dessous.`
      : `_Aucune violation._`,
    ``,
    // Pattern pour extractSpecBadge
    `SPEC_GENERATED: specId=${r.spec_id} title=${r.title} domain=${r.domain} validated=${r.validated} score=${r.score.toFixed(2)}`,
  ].join('\n');
}

function formatValidateSpec(r: ValidateSpecResult): string {
  const status = r.valid ? '✅ Valide' : '❌ Invalide';
  const lines = [
    `**Validation spec** \`${r.spec_id}\` — ${status}`,
    `Score : ${r.score.toFixed(2)} | Blocants : ${r.blocking}`,
  ];
  if (r.violations.length > 0) {
    lines.push('\n**Violations** :');
    r.violations.forEach(v => lines.push(`- [${v.severity.toUpperCase()}] \`${v.rule}\` — ${v.fix_suggestion}`));
  }
  return lines.join('\n');
}

function formatSandboxRun(r: SandboxResult): string {
  const status = r.success ? '✅ Succès' : `❌ Erreur (exit ${r.exit_code})`;
  const lines = [`**Exécution sandbox** — ${status}`];
  if (r.stdout) lines.push('\n**Stdout** :\n```\n' + r.stdout.slice(0, 2000) + '\n```');
  if (r.stderr) lines.push('\n**Stderr** :\n```\n' + r.stderr.slice(0, 500) + '\n```');
  return lines.join('\n');
}

function formatEvaluateQuality(r: Record<string, unknown>): string {
  return [
    `**Qualité du code** — Score : **${r.total_score ?? '?'}/100**`,
    ``,
    `| Critère | Score |`,
    `|---------|-------|`,
    `| Syntaxe | ${(r as any).syntax_score ?? '—'} |`,
    `| Docstrings | ${(r as any).docstring_score ?? '—'} |`,
    `| Type hints | ${(r as any).type_hint_score ?? '—'} |`,
    `| Complexité | ${(r as any).complexity_score ?? '—'} |`,
    `| Conventions | ${(r as any).convention_score ?? '—'} |`,
  ].join('\n');
}

function formatProjectSearch(r: Record<string, unknown>): string {
  const symbols = (r.symbols as unknown[]) ?? [];
  const files   = (r.files   as string[])  ?? [];
  if (symbols.length === 0 && files.length === 0)
    return '_Aucun symbole ni fichier trouvé._';

  const lines = [];
  if (symbols.length > 0) {
    lines.push(`**${symbols.length} symbole(s)** :`);
    (symbols as any[]).slice(0, 8).forEach(s =>
      lines.push(`- \`${s.name}\` (${s.type}) — \`${s.file}:${s.line}\``)
    );
  }
  if (files.length > 0) {
    lines.push(`\n**${files.length} fichier(s)** :`);
    files.slice(0, 8).forEach(f => lines.push(`- \`${f}\``));
  }
  return lines.join('\n');
}

function formatEditBatch(r: EditBatchResult): string {
  if (!r.success) return `❌ **edit_batch échoué** : ${r.errors.join(', ')}`;
  // Pattern TX pour extractTxBadge
  return `✅ **${r.applied} patch(es) appliqué(s)**\n\nTX: ${r.tx_id ?? 'unknown'} | Fichiers: ${r.errors.length > 0 ? '—' : 'voir TX'} | ✅`;
}

function formatAnalyzeError(r: Record<string, unknown>): string {
  return [
    `**Diagnostic** : \`${r.error_type}\` dans \`${r.file}\``,
    ``,
    r.suggestion ? `**Suggestion** : ${r.suggestion}` : '',
    r.fix_prompt  ? `\n**Prompt de correction suggéré** :\n> ${String(r.fix_prompt).slice(0, 200)}` : '',
  ].filter(Boolean).join('\n');
}
```

---

## Tâche 3 — ChatPanel (mise à jour routing + timeout)

### `handleSend` complet avec routing réel

```typescript
async function handleSend(text: string) {
  if (!text.trim() || isStreaming) return;

  // 1. Message user
  appendMessage({ id: uuid(), role: 'user', content: text, createdAt: new Date().toISOString() });
  setIsStreaming(true);
  const abortController = { cancelled: false };

  try {
    // 2. Routing
    const intent = routeIntent(text);

    // 3. Timeout 30s
    const timeoutPromise = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('TIMEOUT')), 30_000)
    );

    // 4. Appel MCP
    const resultRaw = await Promise.race([
      window.lcca.mcpCall(intent.tool, intent.args),
      timeoutPromise,
    ]) as any;

    if (abortController.cancelled) return;

    if (resultRaw?.error) throw new McpError(resultRaw.error.code, resultRaw.error.message);
    const result = JSON.parse(resultRaw?.content?.[0]?.text ?? '{}');

    // 5. Formatage Markdown
    const responseText = formatMcpResponse(intent.tool, result);

    // 6. Extraction badges
    const txBadge   = extractTxBadge(responseText);
    const specBadge = extractSpecBadge(responseText);

    // 7. Streaming simulé
    const msgId = uuid();
    // Ajouter bulle assistant vide (sera remplie par streaming)
    appendMessage({ id: msgId, role: 'assistant', content: '', createdAt: new Date().toISOString(), txBadge, specBadge });

    await simulateStreaming(responseText, msgId, appendStreamToken);
    finalizeStream(msgId);

    // 8. Mise à jour contexte
    if (txBadge?.status === 'committed') {
      addTxRecord(txBadge);
      setModifiedFiles(txBadge.files);
    }
    if (specBadge) {
      refreshSpecs();
    }

  } catch (err) {
    const message = (err as Error).message === 'TIMEOUT'
      ? '⏱ La génération a pris trop longtemps (> 30s). Réessayez ou vérifiez le serveur.'
      : `⚠ Erreur MCP : ${(err as Error).message}`;
    appendMessage({ id: uuid(), role: 'system', content: message, createdAt: new Date().toISOString() });
  } finally {
    setIsStreaming(false);
  }
}
```

### Bouton Annuler (timeout)

Afficher `[Annuler]` pendant le streaming. Si cliqué → `abortController.cancelled = true`
+ `setIsStreaming(false)` + supprimer la bulle assistant en cours de streaming.

---

## Tâche 4 — CommandPalette

### `src/components/CommandPalette.tsx`

Spec : `spec-ui-03-composants.md` section 6.

```typescript
interface Action {
  id: string;
  icon: string;
  label: string;
  shortcut?: string;
  handler: () => void;
}
```

**Liste des actions** (statique + dynamique) :

```typescript
function buildActions(sessions: Session[], specs: SpecSummary[], handlers: Handlers): Action[] {
  return [
    // Actions globales
    { id: 'new-session',     icon: '💬', label: 'Nouvelle session',    shortcut: 'Ctrl+N',  handler: handlers.newSession },
    { id: 'clear-chat',      icon: '🗑', label: 'Effacer le chat',     shortcut: 'Ctrl+L',  handler: handlers.clearChat },
    { id: 'toggle-context',  icon: '▣',  label: 'Afficher/masquer contexte', shortcut: 'Ctrl+\\', handler: handlers.toggleContext },
    { id: 'focus-mode',      icon: '⛶',  label: 'Mode focus',          shortcut: 'Ctrl+⇧F', handler: handlers.focusMode },
    { id: 'restart-server',  icon: '⟳',  label: 'Relancer McpServer',               handler: handlers.restartServer },
    { id: 'settings',        icon: '⚙',  label: 'Paramètres',          shortcut: 'Ctrl+,',  handler: handlers.openSettings },
    { id: 'toggle-theme',    icon: '🌙', label: 'Basculer thème',       shortcut: 'Ctrl+⇧T', handler: handlers.toggleTheme },
    // Sessions récentes (dynamique)
    ...sessions.slice(0, 5).map(s => ({
      id: `session-${s.id}`, icon: '💬', label: `Session : ${s.title}`,
      handler: () => handlers.loadSession(s.id),
    })),
    // Specs récentes (dynamique)
    ...specs.slice(0, 5).map(sp => ({
      id: `spec-${sp.specId}`, icon: '📋', label: `Spec : ${sp.title}`,
      handler: () => handlers.openSpec(sp.specId),
    })),
  ];
}
```

**Fuzzy filter** :
```typescript
function fuzzyFilter(actions: Action[], query: string): Action[] {
  if (!query) return actions;
  const q = query.toLowerCase();
  return actions.filter(a => a.label.toLowerCase().includes(q));
}
```

**JSX** :
```tsx
export function CommandPalette({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const actions = buildActions(/* ... */);
  const filtered = fuzzyFilter(actions, query);

  useEffect(() => setSelectedIndex(0), [query]);

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') setSelectedIndex(i => Math.min(i + 1, filtered.length - 1));
    if (e.key === 'ArrowUp')   setSelectedIndex(i => Math.max(i - 1, 0));
    if (e.key === 'Enter' && filtered[selectedIndex]) {
      filtered[selectedIndex].handler(); onClose();
    }
    if (e.key === 'Escape') onClose();
  };

  return (
    <div className="command-palette-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="command-palette" role="dialog" aria-label="Palette de commandes">
        <input autoFocus value={query} onChange={e => setQuery(e.target.value)}
               onKeyDown={handleKey} placeholder="Rechercher une action…"
               className="command-palette-input" />
        <ul className="command-palette-list" role="listbox">
          {filtered.map((action, i) => (
            <li key={action.id} role="option" aria-selected={i === selectedIndex}
                className={`command-palette-item ${i === selectedIndex ? 'selected' : ''}`}
                onClick={() => { action.handler(); onClose(); }}>
              <span className="cp-icon">{action.icon}</span>
              <span className="cp-label">{action.label}</span>
              {action.shortcut && <span className="cp-shortcut">{action.shortcut}</span>}
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="command-palette-empty">Aucune action trouvée</li>
          )}
        </ul>
      </div>
    </div>
  );
}
```

Intégration dans `App.tsx` : état `showPalette`, ouverture via `useShortcuts('command-palette')`.

---

## Tâche 5 — ErrorBanner

### `src/components/ErrorBanner.tsx`

```tsx
interface ErrorBannerProps {
  status: 'disconnected' | 'error';
  retryIn?: number;           // secondes avant prochaine tentative auto
  onRetryNow: () => void;
}

export function ErrorBanner({ status, retryIn, onRetryNow }: ErrorBannerProps) {
  const msg = status === 'disconnected'
    ? `McpServer déconnecté${retryIn ? ` — reconnexion dans ${retryIn}s` : ''}…`
    : 'McpServer en erreur — vérifiez les logs';

  return (
    <div className="error-banner" role="alert">
      <span className="error-banner-icon">⚠</span>
      <span className="error-banner-msg">{msg}</span>
      <button className="error-banner-btn" onClick={onRetryNow}>
        Relancer maintenant
      </button>
    </div>
  );
}
```

Affiché en haut du `ChatPanel` si `mcpStatus !== 'connected'`.
CSS : fond `var(--error)` atténué, texte `var(--text-primary)`, `position: sticky; top: 0`.

---

## Tâche 6 — Polling status MCP

Dans `contextStore.ts`, ajouter un polling toutes les 3 secondes :

```typescript
startPolling: () => {
  const poll = setInterval(async () => {
    try {
      const s = await (window as any).lcca.mcpStatus();
      set({ mcpStatus: s.status, llmStatus: s.llmStatus ?? 'unknown' });
    } catch {
      set({ mcpStatus: 'error' });
    }
  }, 3000);
  return () => clearInterval(poll);
},
```

Appeler `startPolling()` dans `App.tsx` via `useEffect`.
Le cleanup (return `() => clearInterval`) est géré par React.

---

## Critères d'acceptance Sprint UI-04

| Critère | Validation |
|---------|-----------|
| `@spec refactoriser TransactionManager domain:mcp` → appel `generate_spec` | Manuel |
| Bloc ```python → appel `sandbox_run`, résultat affiché | Manuel |
| `@file orchestrator` → appel `project_search`, résultats listés | Manuel |
| Texte libre → appel `memory_search`, résultats formatés | Manuel |
| Timeout 30s → message d'erreur + bouton Annuler visible | Manuel |
| Ctrl+K ouvre la CommandPalette | Manuel |
| Fuzzy filter dans la CommandPalette | Manuel |
| Navigation ↑/↓ + Enter dans la palette | Manuel |
| ErrorBanner visible si MCP déconnecté | Manuel |
| ErrorBanner disparaît à la reconnexion | Manuel |
| Polling status MCP toutes les 3s | Manuel |
| Erreur MCP -32xxx → bulle système avec code + message | Manuel |

<!-- AI-READY | Sprint UI-04 CommandPalette + Routing MCP + Erreurs | Version 1.0.0 | 2026-04-18 -->
