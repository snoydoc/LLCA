# LCCA SelfImprove V10.5 — Spécification Complète
<!-- AI-READY | LCCA V10.5 | SelfImprovement | Statut : VALIDÉE | Date : 2026-04-23 -->

> **Basée sur** : V10.5 spec consolidée + verdict critique (doc2) + skills projet (001/002/003/004)  
> **Contraintes** : 16 GB RAM · 4 GB VRAM · 100% offline · qwen2.5-coder:3b  
> **Philosophie** : Observer actif + règles déterministes + auto-fix très limité + contrôle humain total

---

## 1. Objectif

Passer d'un pipeline statique (V10) à un système **réactif, traçable et auto-améliorant contrôlé**,
ancré dans les composants existants de LCCA : WAL, TransactionManager, SmartPatcher, KarpathyLoop,
TelemetryStore, ChromaDB.

**Principes non négociables :**

- Lire tous les signaux disponibles (WAL, logs, télémétrie, tests)
- Décisions déterministes uniquement (règles JSON, zéro probabilité)
- Auto-corrections limitées à une whitelist et vérifiées par tests
- Contrôle humain total (dry-run, approve, require_human_ack)
- Traçabilité complète (actions.log write-ahead, patches, borgnes_map)
- 3 modes de couplage adaptés à la puissance machine

---

## 2. Modes de couplage

Choix dans **Paramètres → SelfImprove** de l'UI Adham. Stocké dans `config.toml`.

| Mode | Nom | Comportement | RAM estimée |
|------|-----|--------------|-------------|
| **1** | Lecture seule | Observer + observations JSON. Orchestrator en dry-run uniquement. Aucune action. | ~50 MB |
| **2** | Semi-couplé *(défaut)* | Observer + Orchestrator actifs. Importe types TX, n'appelle pas les agents. Auto-Fix activable manuellement. | ~150 MB |
| **3** | Couplé pipeline | Mode 2 + déclenchement via A2ALocalBus vers CoderAgent. Auto-Fix activé par défaut. | ~300 MB + 1 LLM run |

> Règle : `min_coupling_mode` dans chaque règle JSON — règle ignorée si mode courant insuffisant.

---

## 3. Architecture

```
[WAL / logs / TelemetryStore / pytest]
                │
                ▼
        [Observer daemon]  ──► observations/YYYY-MM-DD-HHMMSS.json
                │                    (écriture atomique .tmp → rename)
                ▼
        [Orchestrator Light]  ──► actions.log (write-ahead CSV)
                │
    ┌───────────┼──────────────┐
    ▼           ▼              ▼
[Coder]*   [Notifier]    [log_only]
(Mode 3)        │
                ▼
        pending_actions.json  ──► lcca approve <id>
                │
        [Auto-Fix Engine]
        (whitelist + SmartPatcher libcst / template string)
                │
        [Educator]  ──► patterns/suggested_*.md
        (suggestions uniquement, jamais d'action autonome)
```

`*` Mode 3 : `A2ALocalBus.publish(TaskContract(...))` vers CoderAgent.

---

## 4. Observer

### 4.1 Fichier : `SelfImprove/engines/observer_daemon.py`

**Classe principale** : `ObserverDaemon`

**Méthodes publiques** :

| Méthode | Signature | Retour |
|---------|-----------|--------|
| `run_once()` | `() → Path \| None` | Chemin du fichier observation écrit |
| `run_daemon()` | `() → None` | Boucle infinie (interval depuis config) |

**Sources** :

| Source | Accès | Données extraites |
|--------|-------|-------------------|
| WAL | `transactions/*.wal` (pathlib glob) | erreur runtime, rollback, intent, error_type |
| Logs | `logs/lcca.log` (tail 5000 lignes) | exceptions, stack traces, timeouts |
| TelemetryStore | API interne V9-09 | tok/s par intent_type, latence par phase |
| pytest | `tests/last_results.json` | tests échoués, flaky, durée |

**Patterns détectés** (extensibles via `observer_patterns.json`) :

| Pattern | Source | Condition |
|---------|--------|-----------|
| `coroutine_never_awaited` | log | regex `coroutine .* was never awaited` |
| `missing_import` | log | regex `ImportError: No module named` |
| `timeout_error` | log/test | `TimeoutError` ou `pytest.TimeoutExpired` |
| `repeated_test_failure` | test | même test échoue ≥ 2× en 24h |
| `slow_intent` | telemetry | tok/s < 50% baseline intent_type |
| `rollback_cluster` | WAL | même error_type en rollback ≥ 3× (archéologie V10) |
| `stagnation_loop` | WAL | même fichier rollback + retry ≥ 2× en session |

**Format de sortie** (`observations/YYYY-MM-DD-HHMMSS.json`) :

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
    }
  ]
}
```

**Écriture atomique obligatoire** :

```python
tmp = obs_path.with_suffix(".tmp")
tmp.write_text(json.dumps(payload, ...), encoding="utf-8")
tmp.rename(obs_path)  # atomique — jamais de JSON corrompu
```

### 4.2 Borgnes Map (héritage V10)

L'Observer alimente `borgnes_map.json` via clustering WAL (ChromaDB existant) :
chaque cluster de rollbacks similaires devient un "borgne cognitif" — zone aveugle du système.

```json
{
  "borgnes": [
    {
      "name": "async-closure-rollbacks",
      "count": 4,
      "intent_sample": "modifie une fonction async avec closure",
      "error_type": "PatchFailed",
      "severity": "high"
    }
  ]
}
```

---

## 5. Orchestrator Light

### 5.1 Fichier : `SelfImprove/engines/orchestrator.py`

**Classe principale** : `OrchestratorLight`

**Constructeur** : `__init__(self, dry_run: bool = False)`

**Méthodes publiques** :

| Méthode | Signature | Retour |
|---------|-----------|--------|
| `run()` | `() → dict` | `{triggered, skipped, matched_rules}` |
| `execute_action()` | `(rule_id, action, target, params) → str` | statut (`success/failed/skipped`) |

**Fenêtre d'observations** : N derniers fichiers JSON (configurable `observation_window`),
ignorés si plus vieux que `observation_max_age_sec`. Signaux fusionnés par pattern (count additionné).

**Grammaire unifiée des règles** (format unique — plus d'incohérence) :

```json
{
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
  "min_coupling_mode": 2,
  "require_human_ack": false,
  "cooldown_sec": 300,
  "max_trigger_per_day": 2
}
```

**Actions supportées** :

| Action | Description | Mode min |
|--------|-------------|----------|
| `retry_coder_once` | Mode 2 : relance directe. Mode 3 : A2ALocalBus TaskContract | 2 |
| `notify_human` | Terminal + pending_actions.json si require_human_ack | 1 |
| `log_only` | actions.log uniquement | 1 |
| `trigger_auto_fix` | Auto-Fix Engine (si activé) | 2 |

**Statuts d'action** : `success` / `failed` / `skipped` / `pending_ack`

**Garde-fous codés en dur** :
- `max_retries = 1` pour `retry_coder_once`
- Verrou fichier `.orchestrator_lock` + timeout 30s en mode `--auto`
- `min_coupling_mode` vérifié avant toute exécution

**Write-ahead obligatoire** : chaque action écrite dans `actions.log` AVANT son exécution.

**Format actions.log** (CSV UTF-8 UTC) :
```
timestamp,rule_id,action,target,status,details
2026-04-23T15:00:00Z,rule_test_retry,retry_coder_once,core/async_worker.py,success,"retry 1/1"
```

### 5.2 pending_actions.json

```json
{
  "actions": [
    {
      "action_id": "550e8400-e29b-41d4-a716-446655440000",
      "timestamp": "2026-04-23T15:05:00Z",
      "rule_id": "rule_notify_on_high_severity",
      "action": "notify_human",
      "target": "core/async_worker.py",
      "params": {},
      "status": "pending",
      "requires_ack": true
    }
  ]
}
```

---

## 6. Auto-Fix Engine

### 6.1 Fichier : `SelfImprove/engines/auto_fix.py`

**Classe principale** : `AutoFixEngine`

**Stratégie de correction** :

| Pattern | Outil | Justification |
|---------|-------|---------------|
| `coroutine_never_awaited` | SmartPatcher (libcst) | Modification syntaxique AST — cohérent avec pipeline Coder |
| `missing_import` | Template string | `import X\n` en tête — pas besoin d'AST |

> `SmartPatcher.apply_patch()` retourne `str` uniquement — n'écrit jamais disque.
> L'AutoFixEngine est le seul responsable de l'écriture via `filesystem:write_file`.

**Conditions d'exécution (TOUTES obligatoires)** :

1. Pattern présent dans `auto_fix_whitelist.json`
2. Mode couplage ≥ 2
3. `.auto_fix_enabled` flag présent
4. Test pytest existant pour le module cible
5. Couverture du fichier cible ≥ 60% (`pytest --cov` → `coverage.json → line_rate`)
6. Tests verts AVANT patch
7. Tests verts APRÈS patch

**Processus** :

```
trigger_auto_fix(pattern_id)
    │
    ▼ log_action(..., status="started")   ← write-ahead
    │
    ▼ vérification whitelist + mode + flag
    │
    ▼ vérification coverage ≥ 60%
    │  échec → log "failed", cooldown 1h, STOP
    │
    ▼ pytest baseline → si rouge → log "skipped", STOP
    │
    ▼ SmartPatcher.apply_patch() ou template string → str
    │
    ▼ snapshot fichier source (backup avant écriture)
    │
    ▼ écriture patch → auto_fixes/YYYY-MM-DD-NNN.patch
    │
    ▼ pytest post-patch
    │
    ├── SUCCÈS → commit branche auto-fix/<pattern>-YYYYMMDD-HHMMSS
    │            tag [AUTO-FIX SAFE]
    │            auto_push = false (jamais)
    │            log "success" + auto_fix_success.log
    │            notify_human
    │
    └── ÉCHEC  → rollback depuis snapshot
                 log "failed"
                 cooldown_override 1h sur règle
```

**Interdictions strictes** :
- ❌ > 1 fichier modifié
- ❌ > 5 lignes de patch
- ❌ Logique métier modifiée
- ❌ Push git automatique
- ❌ Auto-fix si coverage < 60%

---

## 7. Educator

### 7.1 Fichier : `SelfImprove/engines/educator.py`

**Classe principale** : `EducatorSI`

**Méthode publique** : `ingest(source, file_path=None) → Path | None`

**Sources** :
- `auto-fix` : analyse `auto_fixes/*.log` récents
- `borgnes` : analyse `borgnes_map.json` (héritage V10)
- `manual` : fichier passé en argument

**Sortie** : `patterns/suggested_YYYY-MM-DD-NNN.md`

**Règle absolue** : l'Educator ne modifie jamais `orchestrator_rules.json`,
`auto_fix_whitelist.json` ni `prompts/rules.md`. Suggestions uniquement.

---

## 8. CLI (`lcca_si.py`)

| Commande | Description | Mode min |
|----------|-------------|----------|
| `lcca_si observe` | Observer une fois | 1 |
| `lcca_si decide` | Orchestrator | 1 |
| `lcca_si decide --dry-run` | Affiche règles matchées, n'exécute rien | 1 |
| `lcca_si decide --auto` | Mode automatique avec verrou | 2 |
| `lcca_si auto-fix enable\|disable` | Active/désactive Auto-Fix | 2 |
| `lcca_si educator ingest --source` | Suggestion pattern | 1 |
| `lcca_si history [--since] [--action]` | Dernières actions | 1 |
| `lcca_si approve <action_id>` | Valide action pending | 1 |
| `lcca_si borgnes` | Affiche borgnes_map.json | 1 |
| `lcca_si mode <1\|2\|3>` | Change mode couplage | 1 |

---

## 9. Arborescence finale

```
D:\LLMCodeAgent\
├── lcca_si.py                           ← CLI point d'entrée
│
└── SelfImprove\
    ├── SPEC_V10.5.md
    ├── config.toml
    ├── borgnes_map.json
    ├── orchestrator_rules.json
    ├── auto_fix_whitelist.json
    ├── observer_patterns.json
    ├── pending_actions.json
    ├── actions.log                      ← CSV write-ahead
    ├── auto_fix_success.log
    ├── .auto_fix_enabled                ← flag
    ├── .orchestrator_lock               ← verrou mode auto
    ├── si_config.py                     ← loader config.toml
    ├── si_utils.py                      ← atomic_write, log_action, cooldowns
    ├── __init__.py
    │
    ├── engines\
    │   ├── __init__.py
    │   ├── observer_daemon.py
    │   ├── orchestrator.py
    │   ├── auto_fix.py
    │   └── educator.py
    │
    ├── observations\
    │   └── YYYY-MM-DD-HHMMSS.json
    │
    ├── auto_fixes\
    │   ├── YYYY-MM-DD-NNN.patch
    │   └── YYYY-MM-DD-NNN.log
    │
    └── patterns\
        └── suggested_YYYY-MM-DD-NNN.md
```

---

## 10. Garde-fous système

| # | Garde-fou | Implémentation |
|---|-----------|----------------|
| 1 | Aucun auto-fix sans test | existence test + coverage ≥ 60% |
| 2 | Aucun retry infini | max_retries=1 codé en dur |
| 3 | Aucun pattern auto-appris | Educator génère suggestions uniquement |
| 4 | Aucun agent autonome | Orchestrator = règles statiques JSON |
| 5 | Aucune action sans cooldown | cooldown_sec obligatoire |
| 6 | Aucune action sans limite quotidienne | max_trigger_per_day obligatoire |
| 7 | Aucune modification multi-fichiers | vérification ≤ 1 fichier |
| 8 | Aucune corruption JSON | écriture atomique .tmp → rename |
| 9 | Aucune action Mode 1 hors log/notify | min_coupling_mode vérifié |
| 10 | Aucun push git automatique | auto_push = false codé en dur |
| 11 | Dry-run disponible | --dry-run zéro effet de bord |

---

## 11. UI Adham — SelfImprovePanel.tsx

Intégré dans **Paramètres → SelfImprove**. Design system existant (themes.css, Inter/JetBrains Mono, ambre).

**Sections** :
- Mode de couplage : 3 boutons radio styled `badge-acc`/`badge-inf`, description + RAM estimée
- État système : badges `badge-ok`/`badge-err` pour Observer, Orchestrator, Auto-Fix
- Mini-log : 5 dernières lignes `actions.log` avec badges statut
- Suggestions en attente : count `badge-acc` dans nav sidebar si > 0

**Règle IPC** (skill 001) : toute nouvelle méthode IPC = 3 fichiers (`main.ts` + `preload.ts` + composant).

---

## 12. Critères de succès

- ✅ Observer génère des observations exploitables sans erreur
- ✅ Orchestrator ne déclenche jamais de boucle infinie (tests d'intégration)
- ✅ `actions.log` permet de reconstituer exactement chaque décision
- ✅ Auto-fix ne cause aucune régression (benchmark 100 runs)
- ✅ Un humain comprend en < 5 min pourquoi une action a eu lieu
- ✅ `--dry-run` produit une sortie lisible sans effet de bord

---

## 13. Hors scope V10.5

- ❌ Bifurcation Fantôme (V10 Idée 3) — reportée V11
- ❌ Orchestrator adaptatif / probabiliste
- ❌ Auto-modification des prompts
- ❌ Push git automatique
- ❌ Correction > 1 fichier en auto-fix

## 14. Vers V11 (après 30 jours production)

- Bifurcation Fantôme : mode `--phantom` KarpathyLoop
- Orchestrator adaptatif (seuils basés sur historique actions.log)
- Auto-fix élargi (patterns complexes, validation humaine préalable)
- Feedback loop Educator → Coder (supervision stricte)
