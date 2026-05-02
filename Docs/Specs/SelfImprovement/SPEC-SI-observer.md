# LCCA SelfImprove V10.5 — Spécification Technique : Observer
<!-- AI-READY | LCCA V10.5 | SelfImprovement | Module : Observer | Priorité P0 -->

## Responsabilité unique

Collecter **passivement** des signaux depuis WAL, logs, TelemetryStore, pytest.
Aucune action déclenchée par l'Observer. Sortie : fichier JSON horodaté.

---

## Classe : `ObserverDaemon`

Fichier : `SelfImprove/engines/observer_daemon.py`

```python
class ObserverDaemon:
    def __init__(self, cfg: dict | None = None): ...
    def run_once(self) -> Path | None: ...
    def run_daemon(self) -> None: ...      # boucle infinie, interval depuis config
```

---

## Sources de données

### WAL (`transactions/*.wal`)

Chaque fichier WAL est un NDJSON (une ligne JSON par entrée) ou un format propriétaire
lu via `transaction_manager.py`. L'Observer extrait :

- `tx_id`, `intent`, `error_type`, `error_msg`, `files_touched`, `timestamp`
- Rollbacks identifiés par `status == "rolled_back"` ou `status == "failed"`

Pattern **rollback_cluster** : si ≥ 3 WAL avec le même `error_type` sur les 30 derniers jours
→ signal `severity = high`. Ces clusters alimentent aussi `borgnes_map.json`.

Pattern **stagnation_loop** : même `file_path` dans rollback + retry dans la même session → signal `severity = high`.

### Logs (`logs/lcca.log`)

Lecture des N dernières lignes (configurable, défaut 5000). Regex appliqués :

```python
PATTERNS_LOG = {
    "coroutine_never_awaited": re.compile(r"coroutine '(.+)' was never awaited"),
    "missing_import":          re.compile(r"ImportError: No module named '(.+)'"),
    "timeout_error":           re.compile(r"(TimeoutError|pytest\.TimeoutExpired)"),
}
```

Chaque match → signal avec `file`, `line` extraits du contexte si disponible.

### TelemetryStore (V9-09)

Import : `from core.llm_generator import TelemetryStore` (ou équivalent post-REFACTO-11).

Extraction : historique tok/s par `intent_type`. Baseline = moyenne des 20 derniers runs.
Si `tok_s < 0.5 * baseline` → signal `slow_intent`, `severity = medium`.

Pattern : import **tardif** dans la méthode (éviter import circulaire si TelemetryStore
n'est pas encore initialisé au démarrage de l'Observer).

### pytest (`tests/last_results.json`)

Structure attendue :

```json
{
  "status": "pass|fail",
  "tests_run": 18,
  "failures": ["test_foo", "test_bar"],
  "duration_sec": 1.3,
  "coverage": {"file": "core/x.py", "line_rate": 0.78}
}
```

Pattern **repeated_test_failure** : cross-référence avec l'observation précédente
(lire le dernier fichier `observations/*.json`) — si même test en échec → `count += 1`,
`severity = medium` si count ≥ 2.

---

## Format de sortie complet

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

---

## Écriture atomique

```python
def _write_observation(self, obs_dir: Path, payload: dict) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    obs_path = obs_dir / f"{ts}.json"
    tmp = obs_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.rename(obs_path)   # atomique — jamais de JSON corrompu en cas d'interruption
    return obs_path
```

---

## Borgnes Map

En fin de `run_once()`, si des `rollback_cluster` sont détectés :

```python
def _update_borgnes_map(self, clusters: list[dict], borgnes_path: Path) -> None:
    existing = json.loads(borgnes_path.read_text("utf-8")) if borgnes_path.exists() else {"borgnes": []}
    for cluster in clusters:
        # upsert par error_type
        found = next((b for b in existing["borgnes"] if b["error_type"] == cluster["error_type"]), None)
        if found:
            found["count"] += cluster["cluster_size"]
        else:
            existing["borgnes"].append({
                "name": cluster["error_type"].lower().replace("_", "-"),
                "count": cluster["cluster_size"],
                "intent_sample": cluster.get("intent_sample", ""),
                "error_type": cluster["error_type"],
                "severity": "high",
            })
    existing["generated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(borgnes_path, existing)
```

---

## Conventions LCCA obligatoires

- `log.info("msg %s", var)` — jamais de f-strings dans les logs
- Import TelemetryStore en lazy (dans la méthode, pas au module)
- `Path` partout — jamais de `os.path`
- Pas de `bash_tool` — accès disque uniquement via filesystem MCP ou pathlib direct
