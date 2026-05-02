# LCCA SelfImprove V10.5 — Spécification Technique : Educator & UI
<!-- AI-READY | LCCA V10.5 | SelfImprovement | Module : Educator + UI | Priorité P2 -->

## Educator — Responsabilité unique

Analyser les auto-fix réussis et les borgnes (V10) pour **suggérer** des patterns à ajouter.
Ne modifie jamais le système automatiquement.

---

## Classe : `EducatorSI`

Fichier : `SelfImprove/engines/educator.py`

```python
class EducatorSI:
    def __init__(self, cfg: dict | None = None): ...
    def ingest(self, source: str, file_path: str | None = None) -> Path | None: ...
    # source : "auto-fix" | "borgnes" | "manual"
    # retourne : chemin du fichier suggestion créé, ou None
```

---

## Sources d'ingestion

### Source `auto-fix`

Lit `auto_fixes/*.log` (les 10 derniers) et `auto_fix_success.log`.
Pour chaque fix réussi extrait : `pattern_id`, `file_path`, `commit_hash`, `timestamp`.

Si ≥ 3 occurrences du même `pattern_id` → confiance "Haute".
Si 1-2 occurrences → confiance "Moyenne".

### Source `borgnes`

Lit `borgnes_map.json`. Pour chaque borgne avec `count ≥ 3` et `severity = high`
génère une suggestion de type "cognitif" (héritage V10).

### Source `manual`

Lit le fichier passé en argument (`--file`). Analyse libre du contenu.

---

## Format de suggestion

Fichier : `patterns/suggested_YYYY-MM-DD-NNN.md`

```markdown
# Suggestion — [pattern_id]
> Générée le : 2026-04-23 | Source : auto-fix | Type : opérationnel

## Pattern détecté
- **Nom** : `coroutine_never_awaited`
- **Source** : auto-fix du 2026-04-23 sur `core/async_worker.py`
- **Type** : opérationnel | cognitif (borgne V10)

## Correction appliquée (si opérationnel)
```diff
- asyncio.create_task(fetch_data())
+ await asyncio.create_task(fetch_data())
```

## Description du borgne (si cognitif)
[Description du pattern d'échec récurrent identifié dans les WAL]

## Règle généralisable
Toute coroutine retournée par asyncio.create_task doit être awaitée
si elle est utilisée dans la même fonction asynchrone.

## Confiance
Haute (3 occurrences similaires)

## Validation humaine requise
- [ ] Ajouter dans `orchestrator_rules.json`
- [ ] Ajouter dans `auto_fix_whitelist.json` (si pertinent)
- [ ] Ajouter dans `prompts/rules.md` (si borgne cognitif)
```

---

## Règle absolue

L'Educator ne modifie **jamais** :
- `orchestrator_rules.json`
- `auto_fix_whitelist.json`
- `prompts/rules.md`
- Aucun fichier Python

Uniquement des fichiers `.md` dans `SelfImprove/patterns/`.

---

## Numérotation des suggestions

```python
def _next_suggestion_seq(self, patterns_dir: Path) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = list(patterns_dir.glob(f"suggested_{today}-*.md"))
    return len(existing) + 1
```

---

## UI Adham — SelfImprovePanel

### Fichiers à créer/modifier (règle IPC skill 001 : 3 fichiers)

| Fichier | Opération | Contenu |
|---------|-----------|---------|
| `electron/main.ts` | PATCH | Handlers IPC : `si:getStatus`, `si:getHistory`, `si:runCommand` |
| `electron/preload.ts` | PATCH | Expose `window.lcca.si.*` |
| `src/components/SelfImprovePanel.tsx` | CREATE | Composant panneau paramètres |

### IPC handlers (`main.ts`)

```typescript
// si:getStatus — lit config.toml + flags + dernière observation
ipcMain.handle('si:getStatus', async () => {
  const configPath = path.join(SI_DIR, 'config.toml');
  const autoFixFlag = path.join(SI_DIR, '.auto_fix_enabled');
  const obsDir = path.join(SI_DIR, 'observations');
  // ... retourne {coupling_mode, observer_active, auto_fix_enabled, last_obs_ts}
});

// si:getHistory — lit les N dernières lignes de actions.log
ipcMain.handle('si:getHistory', async (_, limit: number = 5) => {
  // parse CSV actions.log, retourne array de {timestamp, rule_id, action, status}
});

// si:runCommand — exécute lcca_si.py avec args
ipcMain.handle('si:runCommand', async (_, command: string) => {
  // spawn lcca_si.py observe | decide --dry-run | mode X
  // retourne {stdout, stderr, exitCode}
});
```

### Composant `SelfImprovePanel.tsx`

Design system (skill 004) : `themes.css`, Inter/JetBrains Mono, tokens ambre.

**Section Mode de couplage :**
```tsx
// 3 boutons radio
const MODES = [
  { id: 1, label: 'Lecture seule', ram: '~50 MB', desc: 'Observer uniquement, dry-run' },
  { id: 2, label: 'Semi-couplé', ram: '~150 MB', desc: 'Observer + Orchestrator (défaut)' },
  { id: 3, label: 'Couplé pipeline', ram: '~300 MB', desc: 'Pipeline complet via A2ABus' },
];
// Actif : badge-acc | Inactif : badge-inf
// Description : JetBrains Mono 10px, t2
// RAM : JetBrains Mono 9px, t3
```

**Section État système :**
```tsx
// badge-ok si actif, badge-err si erreur, badge-inf si inconnu
<StatusBadge label="Observer" status={status.observer_active} />
<StatusBadge label="Orchestrator" status={status.orchestrator_active} />
<StatusBadge label="Auto-Fix" status={status.auto_fix_enabled} />
// Dernière observation : JetBrains Mono 9.5px, t2
```

**Section Mini-log (5 dernières actions) :**
```tsx
// Colonnes : timestamp | rule_id | status (badge-ok/err/inf)
// Lien "Voir tout" → modal actions.log complet
```

**Badge dans nav sidebar :**
```tsx
// Si suggestions en attente (patterns/suggested_*.md non traités) :
// badge-acc avec count, positionné sur l'icône Paramètres
```

**Tokens CSS utilisés (tous depuis themes.css) :**
- `--acc`, `--acc-dim`, `--b-acc` pour mode actif
- `--ok`, `--err`, `--info` pour statuts
- `--t0` à `--t3` pour textes
- `--bg3`, `--bg4` pour fonds sections
- `--b1`, `--b2` pour bordures

**Anti-patterns UI (skill 004)** :
- ❌ Jamais de valeur hardcodée — tout via `themes.css`
- ❌ Jamais de `<form>` HTML — `onClick`/`onChange` uniquement
- ❌ Jamais de bleu primaire — accent = ambre `#F59E0B`
- ❌ Jamais `localStorage` dans l'artifact

---

## Conventions LCCA obligatoires

- `log.info("msg %s", var)` — jamais de f-strings dans les logs
- `Path` partout — jamais `os.path`
- Educator : `run_task(contract)` → thread daemon si ingestion longue
- Déduplication suggestions : `hashlib.sha256(pattern_id + source)[:16]`
