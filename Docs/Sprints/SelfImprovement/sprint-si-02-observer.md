# Sprint SI-02 — Observer Daemon
<!-- AI-READY | LCCA V10.5 | Sprint SI-02 | Priorité P0 | Effort 2j | Statut : 🔲 À FAIRE -->

## Objectif

Implémenter `ObserverDaemon` : collecte passive de signaux depuis WAL, logs LCCA,
TelemetryStore V9-09 et pytest. Sortie : fichier JSON horodaté avec écriture atomique.
Alimentation de `borgnes_map.json` via clustering WAL.

## Contexte

- WAL existant : `D:\LLMCodeAgent\transactions\*.wal` (TransactionManager Sprint 12)
- TelemetryStore : V9-09, accès via `core.llm_generator` (post REFACTO-11)
- `tests/last_results.json` : généré par `pytest --json-report` (existant)
- ChromaDB disponible pour clustering borgnes (collections Palace existantes)
- Dépendance : SI-01 ✅

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `SelfImprove/engines/observer_daemon.py` | CREATE | ~280 lignes |
| 2 | `tests/test_si_02_observer.py` | CREATE | ~120 lignes |

## Spécification détaillée

### Classe `ObserverDaemon`

```python
# -*- coding: utf-8 -*-
"""
SelfImprove — Observer Daemon V10.5
Collecte passive de signaux. Aucune action déclenchée.
"""
from __future__ import annotations
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from SelfImprove.si_config import load_config, get_paths
from SelfImprove.si_utils import atomic_write_json

log = logging.getLogger(__name__)

# Patterns log — compilés une fois au niveau module
_PATTERN_LOG_COROUTINE = re.compile(r"coroutine '(.+)' was never awaited")
_PATTERN_LOG_IMPORT    = re.compile(r"ImportError: No module named '(.+)'")
_PATTERN_LOG_TIMEOUT   = re.compile(r"(TimeoutError|pytest\.TimeoutExpired)")

class ObserverDaemon:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg or load_config()

    def run_once(self) -> Path | None:
        """Collecte tous les signaux et écrit le fichier observation."""
        signals: list[dict] = []
        signals.extend(self._scan_logs())
        signals.extend(self._scan_wal())
        signals.extend(self._scan_telemetry())
        signals.extend(self._scan_test_results())

        if not signals:
            log.info("Observer : aucun signal détecté")
            return None

        payload = {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "signals": signals,
        }

        obs_dir = Path(self._cfg["paths"]["observations_dir"])
        obs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        obs_path = obs_dir / f"{ts}.json"

        atomic_write_json(obs_path, payload)
        log.info("Observer : %s signal(s) écrits dans %s", len(signals), obs_path.name)

        # Mise à jour borgnes_map si rollback_cluster détecté
        clusters = [s for s in signals if s["pattern"] == "rollback_cluster"]
        if clusters:
            self._update_borgnes_map(clusters)

        return obs_path

    def run_daemon(self) -> None:
        """Boucle daemon — tourne indéfiniment, interval depuis config."""
        interval = self._cfg["observer"]["interval_sec"]
        log.info("Observer daemon démarré (interval=%ss)", interval)
        while True:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001
                log.error("Observer daemon — erreur run_once : %s", exc)
            time.sleep(interval)
```

### Méthode `_scan_logs()`

```python
def _scan_logs(self) -> list[dict]:
    log_file = Path(self._cfg["observer"]["log_file"])
    if not log_file.exists():
        return []

    signals = []
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-5000:]  # lecture des 5000 dernières lignes

    for i, line in enumerate(tail):
        # coroutine_never_awaited
        m = _PATTERN_LOG_COROUTINE.search(line)
        if m:
            signals.append(self._make_signal(
                "sig-%03d" % len(signals),
                pattern="coroutine_never_awaited",
                source="log",
                severity="high",
                context={"coroutine_name": m.group(1), "error_message": line.strip()},
            ))
            continue

        # missing_import
        m = _PATTERN_LOG_IMPORT.search(line)
        if m:
            signals.append(self._make_signal(
                "sig-%03d" % len(signals),
                pattern="missing_import",
                source="log",
                severity="medium",
                context={"module_name": m.group(1), "error_message": line.strip()},
            ))
            continue

        # timeout_error
        if _PATTERN_LOG_TIMEOUT.search(line):
            signals.append(self._make_signal(
                "sig-%03d" % len(signals),
                pattern="timeout_error",
                source="log",
                severity="high",
                context={"error_message": line.strip()},
            ))

    # Déduplication par pattern (count)
    return self._deduplicate(signals)
```

### Méthode `_scan_wal()`

```python
def _scan_wal(self) -> list[dict]:
    wal_dir = Path(self._cfg["observer"]["wal_dir"])
    if not wal_dir.exists():
        return []

    rollbacks: dict[str, list[dict]] = {}  # error_type → list de fossils
    stagnation_files: dict[str, int] = {}  # file_path → count

    for wal_file in wal_dir.glob("*.wal"):
        try:
            entries = self._parse_wal(wal_file)
        except Exception as exc:  # noqa: BLE001
            log.debug("WAL parse error %s : %s", wal_file.name, exc)
            continue

        for entry in entries:
            if entry.get("status") not in ("rolled_back", "failed"):
                continue
            error_type = entry.get("error_type", "unknown")
            rollbacks.setdefault(error_type, []).append(entry)

            # Stagnation : même fichier rollback + retry dans session
            for f in entry.get("files_touched", []):
                stagnation_files[f] = stagnation_files.get(f, 0) + 1

    signals = []

    # rollback_cluster : ≥ 3 rollbacks du même error_type
    for error_type, fossils in rollbacks.items():
        if len(fossils) >= 3:
            signals.append(self._make_signal(
                "sig-%03d" % len(signals),
                pattern="rollback_cluster",
                source="wal",
                severity="high",
                cluster_size=len(fossils),
                intent_sample=fossils[0].get("intent", ""),
                error_type=error_type,
            ))

    # stagnation_loop : même fichier ≥ 2 rollbacks
    for file_path, count in stagnation_files.items():
        if count >= 2:
            signals.append(self._make_signal(
                "sig-%03d" % len(signals),
                pattern="stagnation_loop",
                source="wal",
                severity="high",
                file=file_path,
                count=count,
            ))

    return signals
```

### Méthode `_scan_telemetry()`

```python
def _scan_telemetry(self) -> list[dict]:
    # Import tardif — évite import circulaire si TelemetryStore pas initialisé
    try:
        from core.llm_generator import get_telemetry_history  # adapter selon API réelle
    except ImportError:
        log.debug("TelemetryStore non disponible")
        return []

    signals = []
    try:
        history = get_telemetry_history(last_n=20)
        # history : list de {"intent_type": str, "tok_s": float, "ts": str}
        by_intent: dict[str, list[float]] = {}
        for entry in history:
            it = entry.get("intent_type", "unknown")
            by_intent.setdefault(it, []).append(entry.get("tok_s", 0.0))

        for intent_type, values in by_intent.items():
            if len(values) < 3:
                continue
            baseline = sum(values) / len(values)
            recent = values[-1]
            if baseline > 0 and recent < 0.5 * baseline:
                signals.append(self._make_signal(
                    "sig-%03d" % len(signals),
                    pattern="slow_intent",
                    source="telemetry",
                    severity="medium",
                    intent_type=intent_type,
                    tok_s=recent,
                    baseline_tok_s=baseline,
                ))
    except Exception as exc:  # noqa: BLE001
        log.debug("TelemetryStore scan error : %s", exc)

    return signals
```

### Méthode `_scan_test_results()`

```python
def _scan_test_results(self) -> list[dict]:
    results_file = Path(self._cfg["observer"]["test_results_file"])
    if not results_file.exists():
        return []

    try:
        data = json.loads(results_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    if data.get("status") == "pass" or not data.get("failures"):
        return []

    # Cross-référence avec la dernière observation pour détecter repeated_test_failure
    obs_dir = Path(self._cfg["paths"]["observations_dir"])
    prev_failures: set[str] = set()
    prev_obs = sorted(obs_dir.glob("*.json"), reverse=True)
    if prev_obs:
        try:
            prev_data = json.loads(prev_obs[0].read_text("utf-8"))
            for s in prev_data.get("signals", []):
                if s.get("pattern") == "repeated_test_failure":
                    prev_failures.update(s.get("context", {}).get("failures", []))
        except Exception:
            pass

    signals = []
    repeated = [f for f in data.get("failures", []) if f in prev_failures]
    if repeated:
        signals.append(self._make_signal(
            "sig-%03d" % len(signals),
            pattern="repeated_test_failure",
            source="test",
            severity="medium",
            count=len(repeated),
            context={"failures": repeated},
        ))

    return signals
```

### Helpers

```python
@staticmethod
def _make_signal(signal_id: str, pattern: str, source: str,
                 severity: str = "medium", **kwargs) -> dict:
    s = {"id": signal_id, "pattern": pattern, "source": source,
         "severity": severity, "count": kwargs.pop("count", 1)}
    s.update(kwargs)
    return s

@staticmethod
def _deduplicate(signals: list[dict]) -> list[dict]:
    """Fusionne les signaux du même pattern (additionne count)."""
    merged: dict[str, dict] = {}
    for s in signals:
        key = s["pattern"]
        if key not in merged:
            merged[key] = dict(s)
        else:
            merged[key]["count"] = merged[key].get("count", 1) + s.get("count", 1)
    return list(merged.values())

def _parse_wal(self, wal_file: Path) -> list[dict]:
    """Parse un fichier WAL. À adapter selon format réel TransactionManager."""
    entries = []
    for line in wal_file.read_text("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries

def _update_borgnes_map(self, clusters: list[dict]) -> None:
    borgnes_path = Path(self._cfg["paths"]["borgnes_map"])
    existing = {"borgnes": [], "total_wal_fossils": 0, "generated_at": None}
    if borgnes_path.exists():
        try:
            existing = json.loads(borgnes_path.read_text("utf-8"))
        except Exception:
            pass

    for cluster in clusters:
        error_type = cluster.get("error_type", "unknown")
        found = next((b for b in existing["borgnes"]
                      if b.get("error_type") == error_type), None)
        if found:
            found["count"] += cluster.get("cluster_size", 1)
        else:
            existing["borgnes"].append({
                "name": error_type.lower().replace("_", "-"),
                "count": cluster.get("cluster_size", 1),
                "intent_sample": cluster.get("intent_sample", ""),
                "error_type": error_type,
                "severity": "high",
            })

    existing["generated_at"] = datetime.now(timezone.utc).isoformat()
    existing["total_wal_fossils"] = sum(
        b["count"] for b in existing["borgnes"]
    )
    atomic_write_json(borgnes_path, existing)
    log.info("borgnes_map mis à jour : %s borgnes", len(existing["borgnes"]))
```

## Critères d'acceptation

- [ ] `python lcca_si.py observe` crée un fichier `observations/YYYY-MM-DD-HHMMSS.json`
- [ ] Écriture atomique vérifiée : jamais de `.json` sans contenu valide
- [ ] Signal `coroutine_never_awaited` détecté sur un log de test synthétique
- [ ] Signal `rollback_cluster` détecté sur 3 WAL de test synthétiques
- [ ] `borgnes_map.json` mis à jour si rollback_cluster présent
- [ ] TelemetryStore absent → aucun crash (log.debug silencieux)
- [ ] WAL absents → liste vide, pas de crash
- [ ] `run_daemon()` tourne sans fuite mémoire (vérifiable sur 5 cycles)

## Protocole d'exécution

```
1. filesystem:read_text_file SelfImprove/si_config.py   → vérifier imports
2. filesystem:read_text_file SelfImprove/si_utils.py    → vérifier atomic_write_json
3. filesystem:write_file SelfImprove/engines/observer_daemon.py
4. filesystem:write_file tests/test_si_02_observer.py
5. [relire les deux fichiers créés]
6. pytest tests/test_si_02_observer.py -v
7. pytest tests/ -x -q  (régression globale — 1252+ tests attendus)
```

## Tests (`tests/test_si_02_observer.py`)

```python
# Squelette — à compléter en session
class TestObserverDaemon:
    def test_run_once_no_sources(self, tmp_path):
        # config pointant sur dossiers vides → retourne None
    def test_run_once_creates_json(self, tmp_path):
        # log synthétique avec coroutine → crée observations/*.json
    def test_atomic_write_no_corruption(self, tmp_path):
        # interruption simulée → pas de .json corrompu
    def test_scan_logs_coroutine(self, tmp_path):
        # ligne log "coroutine 'foo' was never awaited" → signal detected
    def test_scan_logs_import_error(self, tmp_path):
        # ligne log "ImportError: No module named 'x'" → signal detected
    def test_scan_wal_rollback_cluster(self, tmp_path):
        # 3 WAL avec error_type="PatchFailed" → rollback_cluster signal
    def test_scan_wal_stagnation(self, tmp_path):
        # même fichier dans 2 WAL → stagnation_loop signal
    def test_scan_test_results_repeated(self, tmp_path):
        # même test en échec dans 2 observations → repeated_test_failure
    def test_borgnes_map_updated(self, tmp_path):
        # rollback_cluster → borgnes_map.json mis à jour
    def test_telemetry_absent_silent(self):
        # TelemetryStore absent → [] sans crash
    def test_deduplicate_merges_count(self):
        # 3 signaux même pattern → 1 signal count=3
```

## Mise à jour skills (fin de sprint)

- **001** : pattern "ObserverDaemon — import TelemetryStore en lazy (méthode), _parse_wal NDJSON"
- **002** : `SelfImprove/engines/observer_daemon.py` ajouté à l'arborescence
- **003** : anti-pattern "import TelemetryStore au niveau module → import circulaire"
