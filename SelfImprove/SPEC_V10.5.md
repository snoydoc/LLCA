# LCCA — Spécification Technique V10.5 (Consolidée)
> **Version** : V10.5 — Observer Actif + Orchestrator Light + Auto‑Fix Contrôlé + Traçabilité Renforcée  
> **Date** : 2026-04-23  
> **Statut** : VALIDÉE — prête pour implémentation  
> **Contraintes machine** : 16 GB RAM · 4 GB VRAM Quadro M2000M · 100% offline (Ollama qwen2.5-coder:3b)  
> **Basée sur** : V10.5 spec initiale + verdict critique doc2 + skills projet LCCA (001/002/003/004)

---

## 1. Objectif général

Passer d'un pipeline statique (V10) à un système **réactif, traçable et progressivement auto‑améliorant**, ancré dans les
concepts établis de LCCA (WAL, TransactionManager, SmartPatcher, KarpathyLoop, TelemetryStore), sans introduire de
complexité cognitive incontrôlable ni de dépendance nouvelle.

La V10.5 hérite de la philosophie de la V10 (Archéologie des Rollbacks, Témoin Silencieux) et lui ajoute une couche
d'exécution déterministe : l'Orchestrator Light et l'Auto‑Fix Engine — deux composants qui transforment les *observations*
en *actions contrôlées*, sans jamais perdre le contrôle humain.

**Principes clés :**

- ✅ Lire tous les signaux disponibles (WAL, logs, télémétrie TelemetryStore, tests pytest)
- ✅ Prendre des décisions déterministes à partir de règles explicites (fichier JSON)
- ✅ Permettre des auto‑corrections limitées et sûres (whitelist + SmartPatcher libcst)
- ✅ Maintenir un contrôle humain total (validation préalable, dry‑run, approve)
- ✅ Assurer une traçabilité complète (logs CSV, patches, historique)
- ✅ S'adapter à la puissance machine via 3 modes de couplage configurables dans l'UI

---

## 2. Modes de couplage (nouveau — choix utilisateur dans Settings)

L'une des décisions clés de V10.5 : le système fonctionne sur des machines à ressources limitées (qwen2.5-coder:3b,
4 GB VRAM). L'utilisateur choisit son mode dans le panneau **Paramètres → SelfImprove** de l'UI Adham.

| Mode | Nom | Comportement | Coût CPU/RAM | Recommandé pour |
|------|-----|--------------|--------------|-----------------|
| **1** | Lecture seule | Observer lit WAL+logs, génère observations JSON. Orchestrator s'exécute uniquement en mode `--dry-run`. Aucune action déclenchée. | Minimal (~50 MB RAM) | Machines < 8 GB RAM, session active avec le LLM |
| **2** | Semi-couplé *(défaut)* | Observer + Orchestrator actifs. Importe les types TX (`transaction_types.py`) mais n'appelle jamais les agents directement. Auto‑Fix activable manuellement via `lcca auto-fix enable`. | Modéré (~150 MB RAM) | Machine standard, LLM en veille |
| **3** | Couplé pipeline | Tout le Mode 2 + déclenchement via A2ABus (`retry_coder_once` envoie un `TaskContract` au CoderAgent). Auto‑Fix activé par défaut si whitelist valide. | Élevé (~300 MB RAM + 1 run LLM) | Machine dédiée, pas d'usage interactif simultané |

> **Règle invariante** : le mode est stocké dans `SelfImprove/config.toml` sous `[general] coupling_mode = 2`.
> L'UI lit et écrit ce fichier via MCP `filesystem:write_file`. La valeur est rechargée à chaque exécution de
> `observer_daemon.py` — pas de restart requis.

---

## 3. Architecture globale

```
[Sources] ──► [Observer] ──► observations/*.json
                                │
                                ▼
                        [Orchestrator]  (règles JSON — déterministe)
                                │
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
           [Coder]*        [Notifier]      [Logger]
           (Mode 3)             │               │
                ▼               ▼               ▼
           [Tester]        Terminal/API    actions.log (CSV)
                │
                ▼
        [Auto‑Fix Engine]  (whitelist + SmartPatcher libcst)
                │
                ▼
        [Educator] (suggestions uniquement — jamais d'action autonome)
```

> `*` En Mode 3 uniquement, via `A2ALocalBus.publish(TaskContract(...))`.  
> L'Educator ne reçoit jamais de déclenchement automatique de l'Orchestrator.

---

## 4. Observer (`SelfImprove/engines/observer_daemon.py`)

### 4.1 Rôle

Collecter **passivement** des signaux depuis plusieurs sources. Aucune action déclenchée par l'Observer.
Hérite des concepts du `SilentWitness` (V10) et du `RollbackArcheologist` (V10).

### 4.2 Sources analysées

| Source | Chemin / accès | Données extraites |
|--------|---------------|-------------------|
| WAL Transactions | `D:\LLMCodeAgent\transactions\*.wal` | erreurs runtime, rollbacks, type d'échec, intent |
| Logs LCCA | `D:\LLMCodeAgent\logs\lcca.log` | exceptions, stack traces, timeouts |
| TelemetryStore | API interne `TelemetryStore` (V9-09) | tok/s par intent_type, latence par phase KarpathyLoop |
| Résultats pytest | `D:\LLMCodeAgent\tests\last_results.json` | tests échoués, flaky tests, durée |

### 4.3 Fréquence d'exécution

- **Mode daemon** : toutes les 60 secondes (configurable `config.toml → [observer] interval_sec = 60`)
- **Mode manuel** : `lcca observe` (génère une observation immédiate)

### 4.4 Écriture atomique (correction race condition doc2)

L'Observer **ne jamais écrire directement** un fichier `.json`. Protocole obligatoire :

```python
# OBLIGATOIRE — écriture atomique
tmp_path = obs_path.with_suffix(".tmp")
tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp_path.rename(obs_path)  # rename atomique — jamais de JSON corrompu
```

### 4.5 Format de sortie

**Dossier** : `D:\LLMCodeAgent\SelfImprove\observations\`  
**Nom** : `YYYY-MM-DD-HHMMSS.json`

```json
{
  "version": "1.0",
  "timestamp": "2026-04-23T14:32:00.123Z",
  "signals": [
    {
      "id": "sig-001",
      "pattern": "coroutine_never_awaited",
      "source": "log",
      "file": "core/async_worker.py",
      "line": 42,
      "count": 2,
      "severity": "high",
      "context": {
        "function": "run_task",
        "error_message": "coroutine 'fetch_data' was never awaited"
      }
    },
    {
      "id": "sig-002",
      "pattern": "slow_intent",
      "source": "telemetry",
      "intent_type": "async",
      "tok_s": 12.3,
      "baseline_tok_s": 45.0,
      "severity": "medium"
    },
    {
      "id": "sig-003",
      "pattern": "rollback_cluster",
      "source": "wal",
      "cluster_size": 4,
      "intent_sample": "modifie une fonction async avec closure",
      "error_type": "PatchFailed",
      "severity": "high"
    }
  ]
}
```

### 4.6 Patterns détectés (liste extensible dans `observer_patterns.json`)

| Pattern | Source | Condition |
|---------|--------|-----------|
| `coroutine_never_awaited` | log | regex `coroutine .* was never awaited` |
| `missing_import` | log | regex `ImportError: No module named` |
| `timeout_error` | log / test | `TimeoutError` ou `pytest.TimeoutExpired` |
| `repeated_test_failure` | test JSON | même test échoue ≥ 2 fois en 24h |
| `slow_intent` | telemetry | tok/s < 50% de la baseline de l'intent_type |
| `rollback_cluster` | WAL | même error_type dans rollback ≥ 3 fois (archéologie V10) |
| `stagnation_loop` | WAL | même fichier rollback + retry ≥ 2 fois dans la même session |

---

## 5. Orchestrator Light (`SelfImprove/engines/orchestrator.py`)

### 5.1 Rôle

Lire les observations récentes et appliquer des **règles déterministes** pour décider d'actions.  
Zéro apprentissage. Zéro probabilité. Zéro appel LLM.

### 5.2 Modes d'exécution

- **Manuel** : `lcca decide` (recommandé phase initiale)
- **Dry‑run** : `lcca decide --dry-run` (affiche règles matchées + actions prévues, n'exécute rien)
- **Automatique** : `lcca decide --auto` avec fichier de verrouillage `.orchestrator_lock`

### 5.3 Fenêtre d'observations (correction doc2 — comportement non déterministe)

L'Orchestrator lit **exactement les N derniers fichiers** d'observation, configurable :

```toml
# config.toml
[orchestrator]
observation_window = 3          # nombre de fichiers observation à lire
observation_max_age_sec = 600   # ignorer observations > 10 min
```

Si plusieurs fichiers sont dans la fenêtre, leurs signaux sont **fusionnés par pattern** (count additionné).

### 5.4 Format unifié des règles (correction doc2 — grammaire unique)

**Chemin** : `D:\LLMCodeAgent\SelfImprove\orchestrator_rules.json`

Grammaire **unique** pour toutes les conditions — plus d'incohérence entre `signal_pattern` vs `signal_severity` :

```json
{
  "version": "1.1",
  "rules": [
    {
      "id": "rule_test_retry",
      "description": "Relancer Coder une fois si le même test échoue deux fois de suite",
      "condition": {
        "field": "signal.count",
        "operator": ">=",
        "value": 2,
        "filters": {
          "pattern": "repeated_test_failure",
          "scope": "same_file"
        }
      },
      "action": "retry_coder_once",
      "params": {
        "max_retries": 1,
        "test_filter": "only_failed"
      },
      "require_human_ack": false,
      "cooldown_sec": 300,
      "max_trigger_per_day": 2,
      "min_coupling_mode": 2
    },
    {
      "id": "rule_notify_on_high_severity",
      "description": "Notifier l'humain sur tout signal de sévérité haute",
      "condition": {
        "field": "signal.severity",
        "operator": "==",
        "value": "high",
        "filters": {}
      },
      "action": "notify_human",
      "params": {
        "message_template": "Signal haute sévérité : {pattern} dans {file} (count={count})"
      },
      "require_human_ack": true,
      "cooldown_sec": 600,
      "max_trigger_per_day": 10,
      "min_coupling_mode": 1
    },
    {
      "id": "rule_auto_fix_await",
      "description": "Déclencher auto-fix sur coroutine non awaitée",
      "condition": {
        "field": "signal.count",
        "operator": ">=",
        "value": 1,
        "filters": {
          "pattern": "coroutine_never_awaited"
        }
      },
      "action": "trigger_auto_fix",
      "params": {
        "pattern_id": "coroutine_never_awaited"
      },
      "require_human_ack": false,
      "cooldown_sec": 3600,
      "max_trigger_per_day": 3,
      "min_coupling_mode": 2
    }
  ]
}
```

> **`min_coupling_mode`** : règle ignorée si le mode courant est inférieur. Ex: `min_coupling_mode: 2` → ignorée en Mode 1.

### 5.5 Actions supportées

| Action | Description | Modes |
|--------|-------------|-------|
| `retry_coder_once` | Mode 2 : relance directe. Mode 3 : `A2ALocalBus.publish(TaskContract(...))` vers CoderAgent | 2, 3 |
| `notify_human` | Terminal + `pending_actions.json` si `require_human_ack=true` | 1, 2, 3 |
| `log_only` | Écrit uniquement dans `actions.log` | 1, 2, 3 |
| `trigger_auto_fix` | Déclenche l'Auto‑Fix Engine (si activé et Mode ≥ 2) | 2, 3 |

### 5.6 Gestion des erreurs d'action (correction doc2)

Chaque action retourne un statut enregistré dans `actions.log` :

| Statut | Signification |
|--------|--------------|
| `success` | Action exécutée sans erreur |
| `failed` | Action échouée (exception catchée) — règle mise en cooldown immédiat |
| `skipped` | Règle ignorée (cooldown, max_trigger, mode insuffisant) |
| `pending_ack` | Action mise en attente dans `pending_actions.json` |

Si une action échoue, l'Orchestrator **n'escalade pas** (pas de retry automatique d'action). Il log le statut
`failed` et respecte le `cooldown_sec` normalement.

### 5.7 Structure `pending_actions.json` (correction doc2)

```json
{
  "actions": [
    {
      "action_id": "550e8400-e29b-41d4-a716-446655440000",
      "timestamp": "2026-04-23T15:05:00Z",
      "rule_id": "rule_notify_on_high_severity",
      "action": "notify_human",
      "target": "core/async_worker.py",
      "params": {"message_template": "..."},
      "status": "pending",
      "requires_ack": true
    }
  ]
}
```

Validation via `lcca approve <action_id>` → statut passe à `approved`, action exécutée, log mis à jour.

### 5.8 Garde‑fous obligatoires (codés en dur)

| # | Garde‑fou | Implémentation |
|---|-----------|----------------|
| 1 | Aucun retry infini | `max_retries=1` codé en dur dans `retry_coder_once` |
| 2 | Aucune action sans cooldown | `cooldown_sec` obligatoire dans chaque règle |
| 3 | Aucune action sans limite quotidienne | `max_trigger_per_day` obligatoire |
| 4 | Aucune action en Mode 1 sauf `log_only` et `notify_human` | `min_coupling_mode` vérifié avant exécution |
| 5 | Aucune boucle infinie | Verrou fichier `.orchestrator_lock` + timeout 30s |

### 5.9 Logs d'actions (`actions.log`)

Format CSV, UTF‑8, horodaté UTC :

```
timestamp,rule_id,action,target,status,details
2026-04-23T15:00:00Z,rule_test_retry,retry_coder_once,core/async_worker.py,success,"retry 1/1"
2026-04-23T15:05:00Z,rule_notify_on_high_severity,notify_human,admin,pending_ack,"severity=high"
2026-04-23T15:10:00Z,rule_auto_fix_await,trigger_auto_fix,core/async_worker.py,failed,"no test coverage"
```

> **Règle absolue** : toute action est écrite dans `actions.log` **AVANT** son exécution (write-ahead).

---

## 6. Auto‑Fix Engine (`SelfImprove/engines/auto_fix.py`)

### 6.1 Activation (désactivé par défaut)

```bash
lcca auto-fix enable
lcca auto-fix disable
```

Flag : `SelfImprove/.auto_fix_enabled`

### 6.2 Stratégie de correction : libcst pour syntaxe, string pour imports

Décision technique alignée sur les conventions LCCA (skill 001) :

| Pattern | Outil | Justification |
|---------|-------|--------------|
| `coroutine_never_awaited` | **SmartPatcher (libcst)** | Modification syntaxique d'AST — identique aux patches Coder |
| `missing_import` | **Template string** | `import X\n` en tête de fichier — pas besoin d'AST |

> `SmartPatcher.apply_patch()` retourne `str` uniquement — n'écrit jamais sur disque (règle invariante skill 001).
> L'Auto‑Fix Engine est le seul responsable de l'écriture via `filesystem:write_file` après validation.

### 6.3 Conditions d'exécution (TOUTES obligatoires)

1. Le pattern est présent dans `auto_fix_whitelist.json`
2. La correction est dans la whitelist des templates autorisés
3. Un test pytest existe pour le module concerné
4. **Couverture du fichier cible ≥ 60%** (vérifiée via `pytest --cov` — correction doc2)
5. Les tests passent AVANT correction (état vert connu)
6. Les tests passent APRÈS correction (validation automatique)
7. Le mode de couplage est ≥ 2

### 6.4 Whitelist (`SelfImprove/auto_fix_whitelist.json`)

```json
{
  "version": "1.0",
  "patterns": [
    {
      "id": "coroutine_never_awaited",
      "tool": "smartpatcher",
      "fix_template": "add_await",
      "allowed_files": ["core/*.py", "workers/*.py"],
      "description": "Ajoute await devant une coroutine non awaitée"
    },
    {
      "id": "missing_import",
      "tool": "string_template",
      "fix_template": "add_import",
      "allowed_files": ["**/*.py"],
      "description": "Ajoute un import manquant en tête de fichier"
    }
  ]
}
```

### 6.5 Processus détaillé

1. Orchestrator appelle `trigger_auto_fix(pattern_id)` → `actions.log` écrit en premier
2. Auto‑Fix Engine vérifie la whitelist et le fichier cible
3. **Vérification couverture** : `pytest --cov=<module> --cov-report=json` → `coverage.json` → `line_rate >= 0.60`
4. Si couverture insuffisante → log `failed`, désactivation temporaire 1h, **arrêt**
5. Run pytest baseline → si rouge → log `skipped` (état non vert), **arrêt**
6. Application du patch (SmartPatcher ou template string selon pattern)
7. Patch sauvegardé dans `SelfImprove/auto_fixes/YYYY-MM-DD-NNN.patch`
8. Run pytest sur le module modifié
9. **Si succès** :
   - Commit sur branche `auto-fix/<pattern_id>-YYYYMMDD-HHMMSS` (jamais sur `main` directement)
   - Tag de commit : `[AUTO-FIX SAFE]`
   - `auto_push = false` (pas de push automatique — Mode 3 compris)
   - Log dans `actions.log` (status=`success`) + `auto_fix_success.log`
   - Notification humain
10. **Si échec** :
    - Rollback du fichier source (restauration depuis snapshot pré-patch)
    - Log `actions.log` (status=`failed`)
    - Désactivation de la règle pendant 1h (`cooldown_override`)

### 6.6 Interdictions strictes (codées en dur)

- ❌ Modification de plus d'un fichier (sauf import + un seul appel)
- ❌ Patch de plus de 5 lignes
- ❌ Changement de logique métier
- ❌ Tout patch qui n'est pas purement syntaxique
- ❌ Push git automatique
- ❌ `auto_fix` si couverture < 60% sur le fichier cible

---

## 7. Intégration Tester

Commande unifiée utilisée par l'Auto‑Fix Engine et le retry_coder_once :

```bash
# Run standard
pytest <chemin_du_module> --json-report --report-file=temp_results.json

# Run avec couverture (auto-fix uniquement)
pytest <chemin_du_module> --cov=<module> --cov-report=json --json-report --report-file=temp_results.json
```

Le fichier `tests/last_results.json` est mis à jour après chaque run (manuel ou automatique).

Structure parsée :

```json
{
  "status": "pass",
  "tests_run": 18,
  "failures": [],
  "duration_sec": 1.3,
  "coverage": {
    "file": "core/async_worker.py",
    "line_rate": 0.78
  }
}
```

---

## 8. Educator (suggestions uniquement)

### 8.1 Rôle

Analyser les auto‑fix réussis et les corrections manuelles, suggérer des patterns à ajouter.  
**Ne modifie jamais le système automatiquement.**

### 8.2 Connexion avec V10 — Borgnes Map

L'Educator V10.5 produit deux types de suggestions :

1. **Suggestion opérationnelle** : règle Orchestrator ou pattern whitelist à ajouter (issues auto‑fix)
2. **Suggestion cognitive** (héritage V10) : borgne identifié par clustering WAL — intent_type récurrent en échec

Le fichier `borgnes_map.json` est alimenté par l'Observer (clustering WAL via ChromaDB) et lu par l'Educator.

### 8.3 Déclenchement (manuel uniquement)

```bash
lcca educator ingest --source auto-fix       # analyse les derniers auto-fix
lcca educator ingest --source borgnes        # analyse borgnes_map.json (V10)
lcca educator ingest --source manual --file <path>
```

### 8.4 Sortie — `SelfImprove/patterns/suggested_YYYY-MM-DD-NNN.md`

```markdown
# Suggestion — [pattern_id]

## Pattern détecté
- **Nom** : `missing_await`
- **Source** : auto-fix du 2026-04-23 sur `async_worker.py`
- **Type** : opérationnel | cognitif (borgne V10)

## Correction appliquée
[diff si opérationnel | description du borgne si cognitif]

## Règle généralisable
[description]

## Confiance
Haute | Moyenne | Faible (N occurrences)

## Validation humaine requise
- [ ] Ajouter dans `orchestrator_rules.json`
- [ ] Ajouter dans `auto_fix_whitelist.json` (si pertinent)
- [ ] Ajouter dans `prompts/rules.md` (si borgne cognitif)
```

L'Educator ne modifie jamais ces fichiers.

---

## 9. CLI (`lcca.py` à la racine)

| Commande | Description | Mode min |
|----------|-------------|----------|
| `lcca observe` | Observer une fois, écrit observation JSON | 1 |
| `lcca decide` | Orchestrator sur dernière observation | 1 |
| `lcca decide --dry-run` | Affiche règles matchées + actions, n'exécute rien | 1 |
| `lcca decide --auto` | Mode automatique (vérifie verrou) | 2 |
| `lcca auto-fix enable` | Active l'auto‑fix | 2 |
| `lcca auto-fix disable` | Désactive | 2 |
| `lcca educator ingest` | Génère une suggestion de pattern | 1 |
| `lcca history` | 20 dernières actions | 1 |
| `lcca history --since yesterday` | Filtre par date | 1 |
| `lcca history --action retry_coder_once` | Filtre par type | 1 |
| `lcca approve <action_id>` | Valide action en attente (`require_human_ack=true`) | 1 |
| `lcca borgnes` | Affiche la borgnes_map.json (héritage V10) | 1 |
| `lcca mode <1|2|3>` | Change le mode de couplage et met à jour `config.toml` | 1 |

---

## 10. Traçabilité

### 10.1 Arborescence finale

```
D:\LLMCodeAgent\SelfImprove\
├── SPEC_V10.5.md                        ← ce fichier
├── config.toml                          ← configuration générale
├── borgnes_map.json                     ← carte des angles morts (héritage V10)
├── orchestrator_rules.json              ← règles déterministes
├── auto_fix_whitelist.json              ← patterns auto-fix autorisés
├── observer_patterns.json               ← patterns détection extensibles
├── pending_actions.json                 ← actions en attente d'ACK humain
├── actions.log                          ← CSV write-ahead de toutes les actions
├── auto_fix_success.log                 ← log succès auto-fix
├── .auto_fix_enabled                    ← flag activation auto-fix
├── .orchestrator_lock                   ← verrou mode automatique
│
├── engines\
│   ├── observer_daemon.py               ← Observer (WAL + logs + telemetry + tests)
│   ├── orchestrator.py                  ← Orchestrator Light (règles JSON)
│   ├── auto_fix.py                      ← Auto-Fix Engine (SmartPatcher + templates)
│   └── educator.py                      ← Educator (suggestions uniquement)
│
├── observations\
│   └── 2026-04-23-143200.json           ← une observation par run
│
├── auto_fixes\
│   ├── 2026-04-23-001.patch             ← patch appliqué
│   └── 2026-04-23-001.log               ← log détaillé du fix
│
└── patterns\
    └── suggested_2026-04-23-001.md      ← suggestions Educator
```

### 10.2 Règles de traçabilité

- **Toute action** est écrite dans `actions.log` **AVANT** son exécution (write-ahead)
- **Toute modification de fichier** (auto‑fix) est accompagnée d'un `.patch` + un `.log`
- **Toute décision humaine** (`lcca approve`) est journalisée
- Les logs sont UTF‑8, horodatés UTC
- Les fichiers d'observation utilisent le rename atomique `.tmp` → `.json`

---

## 11. Garde‑fous système (liste exhaustive)

| # | Garde‑fou | Implémentation |
|---|-----------|----------------|
| 1 | Aucun auto‑fix sans test préalable | Vérification existence test + coverage ≥ 60% |
| 2 | Aucun retry infini | `max_retries=1` codé en dur |
| 3 | Aucun pattern auto‑appris | Educator ne modifie que des fichiers de suggestion |
| 4 | Aucun agent autonome | Orchestrator exécute uniquement des règles statiques |
| 5 | Aucune action sans cooldown | `cooldown_sec` obligatoire dans chaque règle |
| 6 | Aucune action sans limite quotidienne | `max_trigger_per_day` obligatoire |
| 7 | Aucune modification multi‑fichiers en auto‑fix | Vérification ≤ 1 fichier avant patch |
| 8 | Aucune corruption JSON | Écriture atomique `.tmp` → rename |
| 9 | Aucune action en Mode 1 hors log/notify | `min_coupling_mode` vérifié à chaque règle |
| 10 | Aucun push git automatique | `auto_push = false` codé en dur |
| 11 | Dry-run disponible | `lcca decide --dry-run` — zéro effet de bord |

---

## 12. UI Adham — Panneau SelfImprove (Paramètres)

Intégration dans le design system existant (skill 004 — `themes.css`, Inter/JetBrains Mono, tokens ambre).

### Composant `SelfImprovePanel.tsx`

Accessible depuis `Paramètres → SelfImprove` (nouvelle entrée dans `CommandPalette`).

**Section Mode de couplage :**
- Toggle 3 états (boutons radio styled `badge-acc` pour actif, `badge-inf` pour inactif)
- Description de chaque mode sous les boutons (JetBrains Mono 10px, `t2`)
- Indicateur RAM estimé (JetBrains Mono 9px, `t3`)

**Section État système :**
- Badge `badge-ok` / `badge-err` pour : Observer, Orchestrator, Auto-Fix
- Dernière observation : timestamp JetBrains Mono 9.5px `t2`
- Bouton `lcca observe` → déclenche via MCP `run_lcca_command`

**Section Dernières actions (mini-log) :**
- 5 dernières lignes de `actions.log` affichées
- Colonnes : timestamp | rule_id | status (`badge-ok`/`badge-err`/`badge-inf`)
- Lien "Voir tout" → ouvre `actions.log` dans un modal

**Section Suggestions en attente :**
- Liste des `patterns/suggested_*.md` non traités
- Badge count `badge-acc` dans la nav sidebar si > 0

> Toute nouvelle méthode IPC suivra la règle skill 001 : 3 fichiers touchés (main.ts + preload.ts + composant).

---

## 13. Plan d'implémentation (phases)

| Phase | Livrable | Dépendance | Durée estimée |
|-------|----------|------------|---------------|
| **1** | `config.toml` + structure dossiers + `lcca.py` CLI squelette | — | 0.5j |
| **2** | Observer : lecture WAL + logs + TelemetryStore | — | 2j |
| **3** | `lcca observe` + écriture atomique | Phase 2 | 0.5j |
| **4** | Orchestrator : grammaire unifiée + `--dry-run` | Phase 2 | 1.5j |
| **5** | `lcca decide` + `pending_actions.json` + `lcca approve` | Phase 4 | 0.5j |
| **6** | Auto‑Fix Engine : SmartPatcher libcst + template string | Phase 5 | 2j |
| **7** | Intégration Tester (pytest + coverage) | — | 0.5j |
| **8** | Educator : suggestions + borgnes_map | Phase 6 | 1j |
| **9** | UI `SelfImprovePanel.tsx` + IPC | Phase 4 | 1j |
| **10** | Modes couplage 1/2/3 (A2ABus en Mode 3) | Phase 5 | 1j |
| **11** | Documentation utilisateur | — | 0.5j |

**Total estimé** : 11 jours (une personne). Phases 1→5 = MVP fonctionnel en 5 jours.

---

## 14. Hors scope (V10.5)

- ❌ MetaOrchestrator intelligent ou décisions probabilistes
- ❌ Auto‑modification des prompts
- ❌ Bifurcation Fantôme (V10 — reportée en V11)
- ❌ Orchestration multi‑agents dynamique
- ❌ Correction de plus d'un fichier en auto‑fix
- ❌ Push git automatique
- ❌ Injection automatique de patterns dans le Coder

---

## 15. Vers V11 (non implémentée)

Après **30 jours minimum en production** avec V10.5 validée :

- Bifurcation Fantôme (V10 Idée 3) — mode `--phantom` sur KarpathyLoop
- Orchestrator adaptatif (ajustement seuils basé sur historique `actions.log`)
- Auto‑fix élargi (patterns plus complexes, toujours avec validation humaine)
- Feedback loop Educator → Coder (sous supervision stricte)

---

## 16. Critères de succès V10.5

Le système est considéré **opérationnel** si :

- ✅ Observer tourne sans erreur et génère des observations exploitables
- ✅ Orchestrator ne déclenche **jamais** de boucle infinie (vérifié par tests d'intégration)
- ✅ `actions.log` permet de reconstituer exactement chaque décision
- ✅ Auto‑fix ne cause **aucune régression** sur les tests existants (benchmark 100 runs)
- ✅ Un humain comprend **en moins de 5 minutes** pourquoi une action a eu lieu
- ✅ `--dry-run` produit une sortie lisible sans effet de bord

---

## Résumé exécutif

> **V10.5 = Observer actif (WAL + telemetry + tests) + règles déterministes + auto‑fix très limité (libcst/templates)
> + suggestions humaines + 3 modes de couplage selon la puissance machine.**
>
> L'architecture est entièrement alignée sur les conventions LCCA existantes :
> SmartPatcher pour les patches, TransactionManager WAL pour la traçabilité,
> TelemetryStore pour les signaux de performance, ChromaDB pour les borgnes cognitifs (V10).
> On ne perd jamais le contrôle. On gagne en réactivité et en traçabilité.
> Toute la complexité est maîtrisée par des fichiers de configuration plats et des logs CSV.

**Prochaine étape** : Phase 1 — `config.toml` + structure dossiers + `lcca.py` CLI squelette.
