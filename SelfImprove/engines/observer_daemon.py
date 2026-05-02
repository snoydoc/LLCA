# -*- coding: utf-8-sig -*-
"""
SelfImprove — Observer Daemon V10.5
Collecte passive de signaux depuis WAL, logs LCCA, TelemetryStore, pytest.
Aucune action déclenchée par ce module.

Conforme aux conventions LCCA (skill 001) :
  - log.info("msg %s", var) — jamais de f-strings dans les logs
  - Path partout — jamais os.path
  - Import TelemetryStore en lazy (méthode) — évite import circulaire
  - Écriture JSON via atomic_write_json uniquement
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from SelfImprove.si_config import load_config
from SelfImprove.si_utils import atomic_write_json

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns regex — compilés une fois au niveau module (PAS dans les méthodes)
# ---------------------------------------------------------------------------
_RE_COROUTINE = re.compile(r"coroutine '(.+)' was never awaited")
_RE_IMPORT    = re.compile(r"ImportError: No module named '(.+)'")
_RE_TIMEOUT   = re.compile(r"(TimeoutError|pytest\.TimeoutExpired)")

# Nombre de lignes de log lues en tail
_LOG_TAIL_LINES = 5000


class ObserverDaemon:
    """Collecte passive de signaux. Écrit un fichier JSON par exécution."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg = cfg or load_config()

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    def run_once(self) -> Path | None:
        """Collecte tous les signaux et écrit le fichier observation.

        Retourne le chemin du fichier écrit, ou None si aucun signal détecté.
        """
        signals: list[dict[str, Any]] = []
        signals.extend(self._scan_logs())
        signals.extend(self._scan_wal())
        signals.extend(self._scan_telemetry())
        signals.extend(self._scan_test_results())

        # Déduplication globale (par pattern)
        signals = _deduplicate(signals)

        if not signals:
            log.info("Observer : aucun signal détecté")
            return None

        payload: dict[str, Any] = {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "signals": signals,
        }

        obs_dir = Path(self._cfg["paths"]["observations_dir"])
        obs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        obs_path = obs_dir / ("%s.json" % ts)

        atomic_write_json(obs_path, payload)
        log.info("Observer : %s signal(s) écrits dans %s", len(signals), obs_path.name)

        # Mise à jour borgnes_map si des rollback_cluster sont détectés
        clusters = [s for s in signals if s["pattern"] == "rollback_cluster"]
        if clusters:
            self._update_borgnes_map(clusters)

        return obs_path

    def run_daemon(self) -> None:
        """Boucle infinie daemon — interval depuis config.toml [observer] interval_sec."""
        interval = int(self._cfg["observer"].get("interval_sec", 60))
        log.info("Observer daemon démarré (interval=%ss)", interval)
        while True:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001
                log.error("Observer daemon — erreur run_once : %s", exc)
            time.sleep(interval)

    # ------------------------------------------------------------------
    # Sources de données
    # ------------------------------------------------------------------

    def _scan_logs(self) -> list[dict[str, Any]]:
        """Lit les N dernières lignes du log LCCA et extrait les signaux."""
        log_file = Path(self._cfg["observer"]["log_file"])
        if not log_file.exists():
            log.debug("Log LCCA absent : %s", log_file)
            return []

        try:
            content = log_file.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            log.error("Lecture log LCCA échouée : %s", exc)
            return []

        tail = content.splitlines()[-_LOG_TAIL_LINES:]
        signals: list[dict[str, Any]] = []

        for line in tail:
            m = _RE_COROUTINE.search(line)
            if m:
                signals.append(_make_signal(
                    pattern="coroutine_never_awaited",
                    source="log",
                    severity="high",
                    context={"coroutine_name": m.group(1), "error_message": line.strip()},
                ))
                continue

            m = _RE_IMPORT.search(line)
            if m:
                signals.append(_make_signal(
                    pattern="missing_import",
                    source="log",
                    severity="medium",
                    context={"module_name": m.group(1), "error_message": line.strip()},
                ))
                continue

            if _RE_TIMEOUT.search(line):
                signals.append(_make_signal(
                    pattern="timeout_error",
                    source="log",
                    severity="high",
                    context={"error_message": line.strip()},
                ))

        return signals

    def _scan_wal(self) -> list[dict[str, Any]]:
        """Analyse les fichiers WAL pour détecter rollback_cluster et stagnation_loop."""
        wal_dir = Path(self._cfg["observer"]["wal_dir"])
        if not wal_dir.exists():
            log.debug("WAL dir absent : %s", wal_dir)
            return []

        # error_type → liste de fossils de rollback
        rollbacks: dict[str, list[dict[str, Any]]] = {}
        # file_path → count de rollbacks impliquant ce fichier
        stagnation_files: dict[str, int] = {}

        for wal_file in sorted(wal_dir.glob("*.wal")):
            try:
                entries = _parse_wal(wal_file)
            except Exception as exc:  # noqa: BLE001
                log.debug("WAL parse error %s : %s", wal_file.name, exc)
                continue

            for entry in entries:
                if entry.get("status") not in ("rolled_back", "failed"):
                    continue
                error_type = entry.get("error_type", "unknown")
                rollbacks.setdefault(error_type, []).append(entry)

                for f in entry.get("files_touched", []):
                    stagnation_files[f] = stagnation_files.get(f, 0) + 1

        signals: list[dict[str, Any]] = []

        # rollback_cluster : ≥ 3 rollbacks du même error_type
        for error_type, fossils in rollbacks.items():
            if len(fossils) >= 3:
                sample_intent = fossils[0].get("intent", "")
                signals.append(_make_signal(
                    pattern="rollback_cluster",
                    source="wal",
                    severity="high",
                    count=len(fossils),
                    cluster_size=len(fossils),
                    intent_sample=sample_intent,
                    error_type=error_type,
                ))

        # stagnation_loop : même fichier ≥ 2 rollbacks
        for file_path, count in stagnation_files.items():
            if count >= 2:
                signals.append(_make_signal(
                    pattern="stagnation_loop",
                    source="wal",
                    severity="high",
                    count=count,
                    file=file_path,
                ))

        return signals

    def _scan_telemetry(self) -> list[dict[str, Any]]:
        """Détecte les intents anormalement lents via TelemetryStore.

        Import en lazy — évite import circulaire si TelemetryStore non initialisé.
        """
        try:
            # Adapter le nom exact selon l'API TelemetryStore V9-09
            from core.llm_generator import get_telemetry_history  # type: ignore[import]
        except ImportError:
            log.debug("TelemetryStore non disponible — scan telemetry ignoré")
            return []

        signals: list[dict[str, Any]] = []
        try:
            history: list[dict[str, Any]] = get_telemetry_history(last_n=20)
            by_intent: dict[str, list[float]] = {}
            for entry in history:
                it = entry.get("intent_type", "unknown")
                toks = entry.get("tok_s", 0.0)
                by_intent.setdefault(it, []).append(float(toks))

            for intent_type, values in by_intent.items():
                if len(values) < 3:
                    continue
                baseline = sum(values) / len(values)
                recent = values[-1]
                if baseline > 0 and recent < 0.5 * baseline:
                    signals.append(_make_signal(
                        pattern="slow_intent",
                        source="telemetry",
                        severity="medium",
                        intent_type=intent_type,
                        tok_s=recent,
                        baseline_tok_s=round(baseline, 2),
                    ))
        except Exception as exc:  # noqa: BLE001
            log.debug("TelemetryStore scan error : %s", exc)

        return signals

    def _scan_test_results(self) -> list[dict[str, Any]]:
        """Détecte les tests en échec répété en cross-référençant la dernière observation."""
        results_file = Path(self._cfg["observer"]["test_results_file"])
        if not results_file.exists():
            log.debug("last_results.json absent")
            return []

        try:
            data: dict[str, Any] = json.loads(results_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.error("Lecture last_results.json échouée : %s", exc)
            return []

        if data.get("status") == "pass" or not data.get("failures"):
            return []

        current_failures: set[str] = set(data.get("failures", []))

        # Récupération des échecs de la dernière observation
        obs_dir = Path(self._cfg["paths"]["observations_dir"])
        prev_failures: set[str] = set()
        prev_obs_files = sorted(obs_dir.glob("*.json"), reverse=True)
        if prev_obs_files:
            try:
                prev_data = json.loads(prev_obs_files[0].read_text(encoding="utf-8"))
                for sig in prev_data.get("signals", []):
                    if sig.get("pattern") == "repeated_test_failure":
                        prev_failures.update(sig.get("context", {}).get("failures", []))
            except Exception as exc:  # noqa: BLE001
                log.debug("Lecture observation précédente échouée : %s", exc)

        repeated = sorted(current_failures & prev_failures)
        if not repeated:
            return []

        return [_make_signal(
            pattern="repeated_test_failure",
            source="test",
            severity="medium",
            count=len(repeated),
            context={"failures": repeated},
        )]

    # ------------------------------------------------------------------
    # Borgnes Map (héritage V10)
    # ------------------------------------------------------------------

    def _update_borgnes_map(self, clusters: list[dict[str, Any]]) -> None:
        """Met à jour borgnes_map.json avec les nouveaux clusters WAL détectés."""
        borgnes_path = Path(self._cfg["paths"]["borgnes_map"])
        existing: dict[str, Any] = {
            "version": "1.0",
            "borgnes": [],
            "total_wal_fossils": 0,
            "generated_at": None,
        }
        if borgnes_path.exists():
            try:
                existing = json.loads(borgnes_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.error("Lecture borgnes_map.json échouée : %s", exc)

        for cluster in clusters:
            error_type = cluster.get("error_type", "unknown")
            found = next(
                (b for b in existing["borgnes"] if b.get("error_type") == error_type),
                None,
            )
            if found:
                found["count"] = found.get("count", 0) + cluster.get("cluster_size", 1)
            else:
                existing["borgnes"].append({
                    "name": error_type.lower().replace("_", "-"),
                    "count": cluster.get("cluster_size", 1),
                    "intent_sample": cluster.get("intent_sample", ""),
                    "error_type": error_type,
                    "severity": "high",
                })

        existing["generated_at"] = datetime.now(timezone.utc).isoformat()
        existing["total_wal_fossils"] = sum(b.get("count", 0) for b in existing["borgnes"])
        atomic_write_json(borgnes_path, existing)
        log.info("borgnes_map mis à jour : %s borgne(s)", len(existing["borgnes"]))


# ---------------------------------------------------------------------------
# Helpers module-level (pas de méthodes statiques — préféré par LCCA)
# ---------------------------------------------------------------------------

def _make_signal(pattern: str, source: str, severity: str = "medium",
                 **kwargs: Any) -> dict[str, Any]:
    """Crée un signal standardisé."""
    sig: dict[str, Any] = {
        "pattern": pattern,
        "source": source,
        "severity": severity,
        "count": kwargs.pop("count", 1),
    }
    sig.update(kwargs)
    return sig


def _deduplicate(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fusionne les signaux du même pattern (additionne count, conserve le premier)."""
    merged: dict[str, dict[str, Any]] = {}
    for sig in signals:
        key = sig["pattern"]
        if key not in merged:
            merged[key] = dict(sig)
        else:
            merged[key]["count"] = merged[key].get("count", 1) + sig.get("count", 1)
    # Renumérotation des IDs
    result = list(merged.values())
    for i, s in enumerate(result):
        s["id"] = "sig-%03d" % i
    return result


def _parse_wal(wal_file: Path) -> list[dict[str, Any]]:
    """Parse un fichier WAL (NDJSON — une entrée JSON par ligne).

    Ignore les lignes invalides silencieusement.
    À adapter si le format WAL de TransactionManager diffère.
    """
    entries: list[dict[str, Any]] = []
    for line in wal_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
