# Sprint SI-01 — Structure + Config + CLI
<!-- AI-READY | LCCA V10.5 | Sprint SI-01 | Priorité P0 | Effort 0.5j | Statut : ✅ TERMINÉ 2026-04-23 -->

## Objectif

Poser toute la structure SelfImprove : dossiers, fichiers de configuration JSON/TOML,
module `si_config.py`, utilitaires communs `si_utils.py`, et CLI complet `lcca_si.py`.

Ce sprint est un **prérequis bloquant** pour tous les sprints SI suivants.

## Contexte

Sprint réalisé en session 2026-04-23 via MCP filesystem. Tous les fichiers créés et validés.

## Fichiers produits

| # | Fichier | Opération | Taille estimée |
|---|---------|-----------|----------------|
| 1 | `D:\LLMCodeAgent\lcca_si.py` | CREATE | ~280 lignes |
| 2 | `SelfImprove\si_config.py` | CREATE | ~80 lignes |
| 3 | `SelfImprove\si_utils.py` | CREATE | ~150 lignes |
| 4 | `SelfImprove\config.toml` | CREATE | ~35 lignes |
| 5 | `SelfImprove\orchestrator_rules.json` | CREATE | 6 règles initiales |
| 6 | `SelfImprove\auto_fix_whitelist.json` | CREATE | 2 patterns initiaux |
| 7 | `SelfImprove\observer_patterns.json` | CREATE | 7 patterns détection |
| 8 | `SelfImprove\pending_actions.json` | CREATE | structure vide |
| 9 | `SelfImprove\borgnes_map.json` | CREATE | structure vide |
| 10 | `SelfImprove\actions.log` | CREATE | header CSV |
| 11 | Dossiers engines/, observations/, auto_fixes/, patterns/ | CREATE | — |

## Spécification (rappel)

### si_config.py
- `load_config()` : charge `config.toml` via `tomllib` (Python 3.11+) + merge avec défauts
- `get_coupling_mode()` : retourne int 1/2/3
- `get_paths()` : retourne dict de Path
- Rechargé à chaque appel (pas de cache) — modification sans restart

### si_utils.py
- `atomic_write_json(path, payload)` : `.tmp` → rename atomique
- `log_action(rule_id, action, target, status, details)` : CSV write-ahead
- `add_pending_action(...)` : ajoute dans `pending_actions.json`
- `approve_pending_action(action_id)` : passe status → "approved"
- `check_and_update_cooldown(rule_id, cooldown_sec, max_per_day)` : retourne bool
- `force_cooldown(rule_id, cooldown_sec)` : force le cooldown après échec

### lcca_si.py — Commandes CLI

| Commande | Fonction |
|----------|----------|
| `observe` | `cmd_observe()` → `ObserverDaemon.run_once()` |
| `decide [--dry-run] [--auto]` | `cmd_decide()` → `OrchestratorLight.run()` |
| `auto-fix enable\|disable` | `cmd_auto_fix()` → flag `.auto_fix_enabled` |
| `educator ingest --source` | `cmd_educator()` → `EducatorSI.ingest()` |
| `history [--since] [--action] [--limit]` | `cmd_history()` → parse CSV |
| `approve <action_id>` | `cmd_approve()` → `approve_pending_action()` |
| `borgnes` | `cmd_borgnes()` → affiche `borgnes_map.json` |
| `mode <1\|2\|3>` | `cmd_mode()` → écrit `config.toml` |

## Critères d'acceptation (tous validés ✅)

- [x] `python lcca_si.py --help` s'affiche sans erreur
- [x] `python lcca_si.py mode 2` modifie `config.toml`
- [x] `python lcca_si.py history` affiche le header CSV vide sans crash
- [x] `python lcca_si.py borgnes` affiche le message "Aucun borgne identifié"
- [x] `python lcca_si.py auto-fix enable` crée `.auto_fix_enabled`
- [x] `python lcca_si.py auto-fix disable` supprime `.auto_fix_enabled`
- [x] Import `SelfImprove.si_config` sans erreur (tomllib absent → défauts)
- [x] `atomic_write_json` : écriture `.tmp` + rename vérifié

## Tests à créer (Sprint SI-07)

```python
# tests/test_si_01.py
def test_load_config_defaults():          # si tomllib absent
def test_load_config_from_toml():         # config.toml présent
def test_get_coupling_mode_bounds():      # mode 1/2/3 uniquement
def test_atomic_write_json():             # .tmp → rename
def test_log_action_creates_csv_row():    # write-ahead
def test_add_pending_action():            # UUID + structure
def test_approve_pending_action():        # status → approved
def test_cooldown_blocks_second_call():   # cooldown_sec=60
def test_max_trigger_per_day():           # max=1 bloqué au 2ème
```

## Mise à jour skills (fin de sprint)

- **001** : ajout règle "SelfImprove — atomic_write_json, log_action write-ahead, cooldown tracker"
- **002** : ajout `lcca_si.py` + `SelfImprove/` dans arborescence
