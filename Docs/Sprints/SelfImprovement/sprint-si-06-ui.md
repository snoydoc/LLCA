# Sprint SI-06 — UI SelfImprovePanel
<!-- AI-READY | LCCA V10.5 | Sprint SI-06 | Priorité P2 | Effort 1j | Statut : 🔲 À FAIRE -->

## Objectif

Intégrer le panneau SelfImprove dans l'UI Adham : 3 modes de couplage, état système,
mini-log actions, badge suggestions en attente. Design system existant (themes.css).

## Contexte

- Dépendance : SI-03 🔲 (IPC lisent actions.log + config.toml)
- Design system : skill 004 — Inter/JetBrains Mono, tokens ambre, themes.css
- Règle IPC skill 001 : toute nouvelle méthode = 3 fichiers (main.ts + preload.ts + composant)
- ContextPanel existant : modèle pour la structure panneau latéral

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `electron/main.ts` | PATCH — 3 handlers IPC si:* | +60 lignes |
| 2 | `electron/preload.ts` | PATCH — expose window.lcca.si.* | +15 lignes |
| 3 | `src/components/SelfImprovePanel.tsx` | CREATE | ~200 lignes |

## Avant d'écrire le moindre code

```
1. filesystem:read_text_file electron/main.ts      → comprendre structure handlers existants
2. filesystem:read_text_file electron/preload.ts   → comprendre contextBridge existant
3. filesystem:read_text_file electron/mcp-timeouts.ts → TOOL_TIMEOUTS pattern
4. filesystem:read_text_file src/styles/themes.css → tokens CSS disponibles
5. filesystem:read_text_file src/components/ContextPanel.tsx → pattern panneau existant
```

## Handlers IPC (`main.ts`)

```typescript
// Timeout SelfImprove dans mcp-timeouts.ts (SOURCE DE VÉRITÉ)
// SI_TIMEOUT = 10_000 (10s pour observe/decide)

ipcMain.handle('si:getStatus', async () => {
  // Lit config.toml + .auto_fix_enabled + dernière observation
  // Retourne: { coupling_mode, auto_fix_enabled, last_obs_ts, pending_count }
});

ipcMain.handle('si:getHistory', async (_, limit: number) => {
  // Parse CSV actions.log (N dernières lignes)
  // Retourne: Array<{ timestamp, rule_id, action, status }>
});

ipcMain.handle('si:runCommand', async (_, command: string) => {
  // spawn: [sys.executable, 'lcca_si.py', ...command.split(' ')]
  // Retourne: { stdout, stderr, exitCode }
  // Timeout: SI_TIMEOUT
});
```

## Composant `SelfImprovePanel.tsx` — Structure

```tsx
export default function SelfImprovePanel() {
  const [status, setStatus] = useState<SIStatus | null>(null);
  const [history, setHistory] = useState<SIAction[]>([]);

  useEffect(() => {
    // Polling 30s (comme educator dans contextStore)
    const load = async () => {
      const s = await window.lcca.si.getStatus();
      const h = await window.lcca.si.getHistory(5);
      setStatus(s); setHistory(h);
    };
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{ padding: '12px 14px' }}>
      <ModeSection status={status} />
      <SystemStateSection status={status} />
      <MiniLogSection history={history} />
    </div>
  );
}
```

### Section Mode de couplage

```tsx
const MODES = [
  { id: 1, label: 'Lecture seule', ram: '~50 MB', desc: 'Observer + dry-run uniquement' },
  { id: 2, label: 'Semi-couplé', ram: '~150 MB', desc: 'Observer + Orchestrator (défaut)' },
  { id: 3, label: 'Couplé pipeline', ram: '~300 MB', desc: 'Pipeline complet via A2ABus' },
];

// Bouton actif : fond var(--acc-dim), bordure var(--b-acc), texte var(--acc)
// Bouton inactif : fond var(--bg4), bordure var(--b1), texte var(--t2)
// Clic → window.lcca.si.runCommand('mode X')
```

### Section État système

```tsx
// badge-ok  : actif (fond rgba(ok,0.1), bordure rgba(ok,0.2), texte ok)
// badge-err : erreur
// badge-inf : inconnu
<StatusRow label="Observer"       active={status?.observer_active} />
<StatusRow label="Orchestrator"   active={status?.orchestrator_active} />
<StatusRow label="Auto-Fix"       active={status?.auto_fix_enabled} />
// Dernière obs : JetBrains Mono 9.5px, var(--t2)
// Bouton "Observer maintenant" → runCommand('observe')
```

### Section Mini-log

```tsx
// 5 dernières lignes de actions.log
// Colonnes : timestamp (JetBrains Mono 9px t3) | rule_id (t2) | badge statut
// Statut success → badge-ok | failed → badge-err | skipped/pending → badge-inf
// Lien "Voir tout" → modal scrollable actions.log complet
```

### Badge sidebar

Dans `Sidebar.tsx` — bouton Paramètres :

```tsx
// Si status.pending_count > 0 :
// <span style={{ background: 'var(--acc)', ... }}>{pending_count}</span>
// positionné en haut-droite du bouton ⚙, JetBrains Mono 9px, var(--bg0)
```

## Critères d'acceptation

- [ ] Panel s'affiche dans Paramètres sans erreur console
- [ ] Mode actif affiché en ambre, autres en gris
- [ ] Clic "mode 1" → `config.toml` mis à jour + UI rafraîchie
- [ ] Bouton "Observer maintenant" → exécute `lcca_si.py observe` + rafraîchit statut
- [ ] Mini-log affiche 5 dernières actions avec badges corrects
- [ ] Badge sidebar apparaît si suggestions en attente
- [ ] Aucune valeur couleur hardcodée — tout via themes.css
- [ ] Dark mode et light mode fonctionnels

## Protocole d'exécution

```
1. [Lire les 5 fichiers listés avant d'écrire]
2. filesystem:edit_file electron/mcp-timeouts.ts  → ajouter SI_TIMEOUT
3. filesystem:edit_file electron/main.ts           → ajouter 3 handlers si:*
4. filesystem:edit_file electron/preload.ts        → exposer window.lcca.si.*
5. filesystem:write_file src/components/SelfImprovePanel.tsx
6. filesystem:edit_file src/components/Sidebar.tsx → badge pending_count
7. [Relire TOUS les fichiers modifiés]
```

## Mise à jour skills (fin de sprint)

- **001** : règle "SelfImprovePanel — polling 30s, window.lcca.si.*, SI_TIMEOUT dans mcp-timeouts.ts"
- **002** : `src/components/SelfImprovePanel.tsx` ajouté à l'arborescence UI
- **004** : ModeSection pattern — 3 boutons radio styled tokens ambre
