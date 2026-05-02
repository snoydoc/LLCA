# Sprint UI-03 — ContextPanel complet (Workspace + Specs + Transactions)
<!-- AI-READY | Sprint UI-03 | Version 1.0.0 | 2026-04-18 -->

## Contexte & objectif

Le ContextPanel était un stub depuis UI-01. Ce sprint l'implémente intégralement :
arbre des fichiers workspace, liste des specs `lcca_specs`, historique des transactions.
C'est ici que les Personas 1 (développeur) et 3 (reviewer) trouvent leur valeur.
On branche aussi `contextStore` sur les vrais appels MCP (`memory_search`, `project_search`).

**Prérequis** : Sprint UI-02 vert.
**Livrable** : ContextPanel complet. Toute spec générée apparaît dans la section Specs.
Tout fichier modifié par une TX apparaît dans Workspace avec badge `[✏]`.

---

## Périmètre

| # | Fichier | Type | Description |
|---|---------|------|-------------|
| 1 | `src/components/ContextPanel.tsx` | UPDATE | Sections complètes |
| 2 | `src/components/FileTree.tsx` | CREATE | Arbre collapsible workspace |
| 3 | `src/components/SpecCard.tsx` | CREATE | Carte résumé spec |
| 4 | `src/components/SpecDetailModal.tsx` | CREATE | Modal body_md + violations |
| 5 | `src/components/TxCard.tsx` | CREATE | Carte transaction historique |
| 6 | `src/components/FileViewModal.tsx` | CREATE | Modal lecture fichier workspace |
| 7 | `src/stores/contextStore.ts` | UPDATE | Actions refresh* branchées MCP |
| 8 | `src/hooks/useMcp.ts` | UPDATE | Ajout `projectSearch` |
| 9 | `src/utils/formatters.ts` | CREATE | formatRelativeTime, formatTxId, formatScore |
| 10 | `src/components/ChatPanel.tsx` | UPDATE | onSpecView → ouvre SpecDetailModal |

---

## Tâche 1 — contextStore.ts (branchement MCP)

### Actions à implémenter (remplacer les stubs)

```typescript
// refreshWorkspace() : appelle project_search pour lister les fichiers
refreshWorkspace: async () => {
  const mcp = getMcpCall(); // accès direct window.lcca (hors hook React)
  try {
    const result = await mcp('project_search', { query: '' });
    const parsed = JSON.parse(result.content[0].text);
    set({ workspaceFiles: parsed.files ?? [] });
  } catch { /* silencieux */ }
},

// refreshSpecs() : appelle memory_search sur lcca_specs
refreshSpecs: async () => {
  const mcp = getMcpCall();
  try {
    const result = await mcp('memory_search', { query: 'spec', n: 10 });
    const parsed = JSON.parse(result.content[0].text);
    const specs = (parsed.specs ?? []).map(entryToSpecSummary);
    set({ activeSpecs: specs });
  } catch { /* silencieux */ }
},

// selectSpec() : récupère le body_md complet depuis la mémoire
selectSpec: async (specId: string) => {
  const mcp = getMcpCall();
  try {
    const result = await mcp('validate_spec', { spec_id: specId });
    const parsed = JSON.parse(result.content[0].text);
    // Note : validate_spec retourne le SpecEntry complet (body_md inclus)
    set({ selectedSpec: parsed });
  } catch { /* silencieux */ }
},
```

**`getMcpCall()`** : helper qui appelle `(window as any).lcca.mcpCall` directement
(hors composant React, utilisé dans les stores Zustand).

**Auto-refresh** : `refreshWorkspace()` et `refreshSpecs()` sont appelés :
1. Au démarrage (dans `App.tsx` via `useEffect`)
2. Après chaque réponse MCP reçue (dans `ChatPanel.handleSend` après `finalizeStream()`)
3. Manuellement via bouton `[⟳]` dans chaque section

### Synchronisation des fichiers modifiés

`contextStore.modifiedFiles` est mis à jour quand un `TxBadge` de status `committed`
est détecté. Dans `ChatPanel.tsx` :

```typescript
useEffect(() => {
  const lastMsg = messages[messages.length - 1];
  if (lastMsg?.txBadge?.status === 'committed') {
    setModifiedFiles(lastMsg.txBadge.files);
    // Auto-effacer après 5 minutes
    setTimeout(() => setModifiedFiles([]), 5 * 60 * 1000);
  }
}, [messages]);
```

---

## Tâche 2 — FileTree

### `src/components/FileTree.tsx`

Affiche l'arborescence de `contextStore.workspaceFiles` (liste de chemins relatifs).
Reconstruction de l'arbre à partir des paths :

```typescript
// Reconstruction : ['core/spec_entry.py', 'core/mcp_server.py', 'tests/test_spec.py']
// →  { core: { 'spec_entry.py': null, 'mcp_server.py': null }, tests: { 'test_spec.py': null } }
function buildTree(files: string[]): FileNode {
  const root: FileNode = {};
  for (const f of files) {
    const parts = f.split('/');
    let node = root;
    for (const part of parts.slice(0, -1)) {
      node[part] ??= {};
      node = node[part] as FileNode;
    }
    node[parts[parts.length - 1]] = null; // feuille = fichier
  }
  return root;
}
```

**Comportement** :
- Dossiers : collapsibles (état local `expanded`, par défaut `core/` ouvert, reste fermé)
- Profondeur max affichée : 3 niveaux
- Fichiers modifiés : badge `[✏]` orange (vérifier contre `contextStore.modifiedFiles`)
- Clic sur fichier → `contextStore.setSelectedFile(path)` → ouvre `FileViewModal`
- Icône `>` / `v` pour expand/collapse
- Tri : dossiers en premier, puis fichiers alphabétiques

```tsx
// Structure JSX cible
function FileTreeNode({ name, node, path, depth }: FileTreeNodeProps) {
  const isDir = node !== null && typeof node === 'object';
  const [expanded, setExpanded] = useState(depth === 0);
  const isModified = modifiedFiles.includes(path);

  if (!isDir) {
    return (
      <div className={`tree-file ${isModified ? 'tree-file-modified' : ''}`}
           onClick={() => openFile(path)} style={{ paddingLeft: depth * 12 }}>
        <span className="tree-file-icon">📄</span>
        <span className="tree-file-name">{name}</span>
        {isModified && <span className="tree-modified-badge" aria-label="Modifié">✏</span>}
      </div>
    );
  }

  return (
    <div className="tree-dir">
      <div className="tree-dir-header" onClick={() => setExpanded(!expanded)}
           style={{ paddingLeft: depth * 12 }}>
        <span className="tree-dir-arrow">{expanded ? '▾' : '▸'}</span>
        <span className="tree-dir-icon">📁</span>
        <span className="tree-dir-name">{name}/</span>
      </div>
      {expanded && Object.entries(node as FileNode).map(([k, v]) => (
        <FileTreeNode key={k} name={k} node={v} path={`${path}/${k}`} depth={depth + 1} />
      ))}
    </div>
  );
}
```

---

## Tâche 3 — SpecCard + SpecDetailModal

### `src/components/SpecCard.tsx`

```tsx
interface SpecCardProps {
  spec: SpecSummary;
  onClick: () => void;
}

export function SpecCard({ spec, onClick }: SpecCardProps) {
  return (
    <div className="spec-card" onClick={onClick} role="button" tabIndex={0}
         onKeyDown={e => e.key === 'Enter' && onClick()}>
      <div className="spec-card-header">
        <span className={`spec-card-status ${spec.validated ? 'valid' : 'invalid'}`}>
          {spec.validated ? '✅' : '⚠'}
        </span>
        <span className="spec-card-title">{spec.title.slice(0, 24)}{spec.title.length > 24 ? '…' : ''}</span>
      </div>
      <div className="spec-card-meta">
        <span className="spec-card-domain">{spec.domain}</span>
        <span className="spec-card-date">{formatRelativeTime(spec.createdAt)}</span>
      </div>
    </div>
  );
}
```

### `src/components/SpecDetailModal.tsx`

Modal fullscreen (sur mobile) ou centrée (desktop, 600px max).

```tsx
interface SpecDetailModalProps {
  specId: string;
  onClose: () => void;
}

export function SpecDetailModal({ specId, onClose }: SpecDetailModalProps) {
  const { selectedSpec, selectSpec } = useContextStore();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    selectSpec(specId).finally(() => setLoading(false));
  }, [specId]);

  const handleExport = () => {
    if (!selectedSpec) return;
    const blob = new Blob([selectedSpec.body_md ?? ''], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `spec-${specId}.md`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-content spec-detail-modal" role="dialog" aria-modal="true">
        <div className="modal-header">
          <h2>📋 {selectedSpec?.title ?? specId}</h2>
          <button onClick={onClose} aria-label="Fermer">×</button>
        </div>

        {loading && <div className="modal-loading">Chargement…</div>}

        {!loading && selectedSpec && (
          <>
            <div className="spec-detail-meta">
              ID: {specId} · {selectedSpec.domain} · v{selectedSpec.version}
              {selectedSpec.score != null && ` · score ${selectedSpec.score.toFixed(2)}`}
            </div>

            <div className="spec-detail-body">
              <MarkdownRenderer content={selectedSpec.body_md ?? ''} />
            </div>

            {selectedSpec.violations?.length > 0 && (
              <div className="spec-detail-violations">
                <h3>Violations ({selectedSpec.violations.length})</h3>
                {selectedSpec.violations.map((v: any, i: number) => (
                  <div key={i} className={`violation violation-${v.severity}`}>
                    <span className="violation-rule">[{v.severity?.toUpperCase()}] {v.rule}</span>
                    <span className="violation-fix"> — {v.fix_suggestion}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="modal-footer">
              <button onClick={handleExport}>Exporter .md</button>
              <button onClick={onClose}>Fermer</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

---

## Tâche 4 — TxCard + TxSection

### `src/components/TxCard.tsx`

```tsx
interface TxCardProps {
  tx: TxRecord;
  onDetail: () => void;
}

export function TxCard({ tx, onDetail }: TxCardProps) {
  const statusIcon = tx.status === 'committed'   ? '✅'
                   : tx.status === 'rolled_back' ? '↩'
                   :                               '⚠';

  return (
    <div className="tx-card" onClick={onDetail} role="button" tabIndex={0}
         onKeyDown={e => e.key === 'Enter' && onDetail()}>
      <span className="tx-card-status">{statusIcon}</span>
      <span className="tx-card-id">{tx.txId.slice(3, 11)}</span>  {/* sans "tx_" */}
      <span className="tx-card-file">{tx.files[0] ?? '—'}</span>
      <span className="tx-card-time">{formatRelativeTime(tx.timestamp)}</span>
    </div>
  );
}
```

**Hover tooltip** : afficher tous les fichiers modifiés via `title={tx.files.join(', ')}`.

**TxSection** dans `ContextPanel` :

```tsx
function TxSection() {
  const { recentTx, refreshTransactions } = useContextStore();
  return (
    <section className="context-section">
      <div className="context-section-header">
        <h3>🔄 Transactions récentes ({recentTx.length})</h3>
        <button onClick={refreshTransactions} aria-label="Rafraîchir">⟳</button>
      </div>
      {recentTx.length === 0
        ? <p className="context-empty">Aucune transaction</p>
        : recentTx.slice(0, 10).map(tx => (
            <TxCard key={tx.txId} tx={tx} onDetail={() => {/* modal V2 */}} />
          ))
      }
    </section>
  );
}
```

**Alimentation de `recentTx`** : dans `ChatPanel`, quand un `TxBadge` committed est détecté,
appeler `contextStore.addTxRecord(badge)`. Limiter à 10 entrées (FIFO).

---

## Tâche 5 — FileViewModal

### `src/components/FileViewModal.tsx`

Modal affichant le contenu d'un fichier workspace en lecture seule.

```tsx
interface FileViewModalProps {
  filePath: string;
  onClose: () => void;
}

export function FileViewModal({ filePath, onClose }: FileViewModalProps) {
  const [content, setContent] = useState<string | null>(null);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    (window as any).lcca.readWorkspaceFile(filePath)
      .then((c: string) => setContent(c))
      .catch((e: Error) => setError(e.message));
  }, [filePath]);

  const lang = filePath.endsWith('.py') ? 'python'
             : filePath.endsWith('.ts') ? 'typescript'
             : filePath.endsWith('.md') ? 'markdown'
             : filePath.endsWith('.json') ? 'json'
             : '';

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-content file-view-modal">
        <div className="modal-header">
          <h2>📄 {filePath}</h2>
          <button onClick={onClose} aria-label="Fermer">×</button>
        </div>
        <div className="modal-body">
          {error   && <p className="modal-error">Erreur : {error}</p>}
          {content && <CodeBlock language={lang} code={content} filename={filePath} />}
        </div>
      </div>
    </div>
  );
}
```

---

## Tâche 6 — ContextPanel (assemblage final)

### `src/components/ContextPanel.tsx`

```tsx
export function ContextPanel() {
  const { workspaceFiles, activeSpecs, recentTx, mcpStatus, refreshWorkspace, refreshSpecs } = useContextStore();
  const [specModalId,  setSpecModalId]  = useState<string | null>(null);
  const [fileModalPath, setFileModalPath] = useState<string | null>(null);

  return (
    <aside className="context-panel" aria-label="Panneau contexte">
      <McpStatusBar />
      <WorkspaceSection onFileClick={setFileModalPath} />
      <SpecsSection onSpecClick={setSpecModalId} />
      <TxSection />

      {specModalId && (
        <SpecDetailModal specId={specModalId} onClose={() => setSpecModalId(null)} />
      )}
      {fileModalPath && (
        <FileViewModal filePath={fileModalPath} onClose={() => setFileModalPath(null)} />
      )}
    </aside>
  );
}
```

---

## Tâche 7 — Formatters utilitaires

### `src/utils/formatters.ts`

```typescript
export function formatRelativeTime(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60)   return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}min`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  const days = Math.floor(s / 86400);
  if (days === 1) return 'hier';
  if (days < 7)  return `il y a ${days} jours`;
  return new Date(isoDate).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}

export function formatTxId(txId: string): string {
  // "tx_a3b4c5d6e7f8" → "a3b4c5d6"
  return txId.replace(/^tx_/, '').slice(0, 8);
}

export function formatScore(score: number): string {
  return score.toFixed(2);
}

export function scoreColor(score: number): string {
  if (score >= 0.8) return 'var(--success)';
  if (score >= 0.5) return 'var(--warning)';
  return 'var(--error)';
}
```

---

## Critères d'acceptance Sprint UI-03

| Critère | Validation |
|---------|-----------|
| FileTree affiche l'arborescence du workspace réel | Manuel |
| Fichiers modifiés après TX ont badge `[✏]` orange | Manuel |
| Clic sur un fichier → FileViewModal avec contenu | Manuel |
| Section Specs affiche les specs de `lcca_specs` | Manuel |
| SpecCard cliquable → SpecDetailModal avec body_md rendu | Manuel |
| Violations affichées dans SpecDetailModal si présentes | Manuel |
| Export .md depuis SpecDetailModal déclenche téléchargement | Manuel |
| TxSection affiche les 10 dernières transactions | Manuel |
| `[⟳]` sur chaque section rafraîchit les données | Manuel |
| ContextPanel masquable via `Ctrl+\` (hérité UI-02) | Manuel |
| Indicateur MCP à jour en temps réel | Manuel |

<!-- AI-READY | Sprint UI-03 ContextPanel complet | Version 1.0.0 | 2026-04-18 -->
