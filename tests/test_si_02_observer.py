# -*- coding: utf-8-sig -*-
"""
Tests — Sprint SI-02 : ObserverDaemon
Couverture : run_once, _scan_logs, _scan_wal, _scan_test_results,
             _update_borgnes_map, _deduplicate, TelemetryStore absent.
Convention LCCA : conftest.py bloque le réseau (autouse), import tardif OK.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from SelfImprove.engines.observer_daemon import (
    ObserverDaemon,
    _deduplicate,
    _make_signal,
    _parse_wal,
)


# ---------------------------------------------------------------------------
# Fixture : config minimale pointant sur tmp_path
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path) -> dict:
    obs_dir = tmp_path / "observations"
    obs_dir.mkdir()
    return {
        "general": {"coupling_mode": 2},
        "observer": {
            "interval_sec": 60,
            "wal_dir": str(tmp_path / "transactions"),
            "log_file": str(tmp_path / "lcca.log"),
            "test_results_file": str(tmp_path / "last_results.json"),
            "patterns_file": str(tmp_path / "observer_patterns.json"),
        },
        "paths": {
            "observations_dir": str(obs_dir),
            "borgnes_map": str(tmp_path / "borgnes_map.json"),
            "self_improve_dir": str(tmp_path),
            "auto_fixes_dir": str(tmp_path / "auto_fixes"),
            "patterns_dir": str(tmp_path / "patterns"),
            "actions_log": str(tmp_path / "actions.log"),
            "pending_actions": str(tmp_path / "pending_actions.json"),
        },
    }


# ---------------------------------------------------------------------------
# Tests run_once — comportement global
# ---------------------------------------------------------------------------

class TestRunOnce:
    def test_run_once_no_sources_returns_none(self, tmp_path):
        """Aucun fichier de source → aucun signal → retourne None."""
        cfg = _make_cfg(tmp_path)
        daemon = ObserverDaemon(cfg=cfg)
        result = daemon.run_once()
        assert result is None

    def test_run_once_creates_json_with_signals(self, tmp_path):
        """Log synthétique avec coroutine → fichier JSON créé dans observations/."""
        cfg = _make_cfg(tmp_path)
        log_file = Path(cfg["observer"]["log_file"])
        log_file.write_text(
            "ERROR coroutine 'my_func' was never awaited\n",
            encoding="utf-8",
        )
        daemon = ObserverDaemon(cfg=cfg)
        result = daemon.run_once()

        assert result is not None
        assert result.exists()
        data = json.loads(result.read_text("utf-8"))
        assert data["version"] == "1.0"
        assert len(data["signals"]) >= 1
        patterns = [s["pattern"] for s in data["signals"]]
        assert "coroutine_never_awaited" in patterns

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        """Après écriture, aucun fichier .tmp ne doit subsister."""
        cfg = _make_cfg(tmp_path)
        log_file = Path(cfg["observer"]["log_file"])
        log_file.write_text("ImportError: No module named 'foo'\n", encoding="utf-8")

        daemon = ObserverDaemon(cfg=cfg)
        daemon.run_once()

        obs_dir = Path(cfg["paths"]["observations_dir"])
        tmp_files = list(obs_dir.glob("*.tmp"))
        assert tmp_files == [], "Fichiers .tmp non nettoyés après atomic_write_json"


# ---------------------------------------------------------------------------
# Tests _scan_logs
# ---------------------------------------------------------------------------

class TestScanLogs:
    def test_scan_logs_coroutine_detected(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        log_file = Path(cfg["observer"]["log_file"])
        log_file.write_text(
            "RuntimeWarning: coroutine 'send_message' was never awaited\n",
            encoding="utf-8",
        )
        daemon = ObserverDaemon(cfg=cfg)
        signals = daemon._scan_logs()

        assert any(s["pattern"] == "coroutine_never_awaited" for s in signals)
        hit = next(s for s in signals if s["pattern"] == "coroutine_never_awaited")
        assert hit["context"]["coroutine_name"] == "send_message"
        assert hit["severity"] == "high"

    def test_scan_logs_import_error_detected(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        log_file = Path(cfg["observer"]["log_file"])
        log_file.write_text(
            "ImportError: No module named 'core.missing_mod'\n",
            encoding="utf-8",
        )
        daemon = ObserverDaemon(cfg=cfg)
        signals = daemon._scan_logs()

        assert any(s["pattern"] == "missing_import" for s in signals)
        hit = next(s for s in signals if s["pattern"] == "missing_import")
        assert hit["context"]["module_name"] == "core.missing_mod"

    def test_scan_logs_absent_returns_empty(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        daemon = ObserverDaemon(cfg=cfg)
        assert daemon._scan_logs() == []

    def test_scan_logs_timeout_detected(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        log_file = Path(cfg["observer"]["log_file"])
        log_file.write_text("FATAL TimeoutError in pipeline\n", encoding="utf-8")
        daemon = ObserverDaemon(cfg=cfg)
        signals = daemon._scan_logs()
        assert any(s["pattern"] == "timeout_error" for s in signals)


# ---------------------------------------------------------------------------
# Tests _scan_wal
# ---------------------------------------------------------------------------

class TestScanWal:
    def _write_wal(self, wal_dir: Path, filename: str, entries: list[dict]) -> None:
        wal_dir.mkdir(parents=True, exist_ok=True)
        content = "\n".join(json.dumps(e) for e in entries)
        (wal_dir / filename).write_text(content, encoding="utf-8")

    def test_scan_wal_rollback_cluster_detected(self, tmp_path):
        """3 rollbacks du même error_type → signal rollback_cluster."""
        cfg = _make_cfg(tmp_path)
        wal_dir = Path(cfg["observer"]["wal_dir"])
        entry = {"status": "rolled_back", "error_type": "PatchFailed",
                 "intent": "fix bug", "files_touched": []}
        for i in range(3):
            self._write_wal(wal_dir, f"tx-{i:03d}.wal", [entry])

        daemon = ObserverDaemon(cfg=cfg)
        signals = daemon._scan_wal()

        assert any(s["pattern"] == "rollback_cluster" for s in signals)
        hit = next(s for s in signals if s["pattern"] == "rollback_cluster")
        assert hit["error_type"] == "PatchFailed"
        assert hit["cluster_size"] >= 3

    def test_scan_wal_stagnation_loop_detected(self, tmp_path):
        """Même fichier dans 2 WAL rolled_back → signal stagnation_loop."""
        cfg = _make_cfg(tmp_path)
        wal_dir = Path(cfg["observer"]["wal_dir"])
        entry = {"status": "rolled_back", "error_type": "SyntaxError",
                 "intent": "refactor", "files_touched": ["core/planner.py"]}
        for i in range(2):
            self._write_wal(wal_dir, f"tx-stag-{i}.wal", [entry])

        daemon = ObserverDaemon(cfg=cfg)
        signals = daemon._scan_wal()

        assert any(s["pattern"] == "stagnation_loop" for s in signals)
        hit = next(s for s in signals if s["pattern"] == "stagnation_loop")
        assert "core/planner.py" in hit["file"]

    def test_scan_wal_absent_dir_returns_empty(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        # wal_dir pointe sur un dossier inexistant
        cfg["observer"]["wal_dir"] = str(tmp_path / "no_such_dir")
        daemon = ObserverDaemon(cfg=cfg)
        assert daemon._scan_wal() == []

    def test_scan_wal_success_entries_ignored(self, tmp_path):
        """Les entrées status=committed ne doivent pas générer de signal."""
        cfg = _make_cfg(tmp_path)
        wal_dir = Path(cfg["observer"]["wal_dir"])
        entry = {"status": "committed", "error_type": "none", "files_touched": []}
        for i in range(5):
            self._write_wal(wal_dir, f"ok-{i}.wal", [entry])

        daemon = ObserverDaemon(cfg=cfg)
        signals = daemon._scan_wal()
        assert signals == []


# ---------------------------------------------------------------------------
# Tests _scan_test_results
# ---------------------------------------------------------------------------

class TestScanTestResults:
    def test_repeated_test_failure_detected(self, tmp_path):
        """Même test en échec dans 2 observations → repeated_test_failure."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])

        # Observation précédente avec un échec
        prev_obs = {
            "version": "1.0",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "signals": [{
                "id": "sig-000",
                "pattern": "repeated_test_failure",
                "source": "test",
                "severity": "medium",
                "count": 1,
                "context": {"failures": ["tests/test_planner.py::test_foo"]},
            }],
        }
        (obs_dir / "2026-01-01-000000.json").write_text(
            json.dumps(prev_obs), encoding="utf-8"
        )

        # Résultats actuels avec le même test en échec
        results = {"status": "fail", "failures": ["tests/test_planner.py::test_foo"]}
        Path(cfg["observer"]["test_results_file"]).write_text(
            json.dumps(results), encoding="utf-8"
        )

        daemon = ObserverDaemon(cfg=cfg)
        signals = daemon._scan_test_results()

        assert any(s["pattern"] == "repeated_test_failure" for s in signals)
        hit = next(s for s in signals if s["pattern"] == "repeated_test_failure")
        assert "tests/test_planner.py::test_foo" in hit["context"]["failures"]

    def test_no_failures_returns_empty(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        results = {"status": "pass", "failures": []}
        Path(cfg["observer"]["test_results_file"]).write_text(
            json.dumps(results), encoding="utf-8"
        )
        daemon = ObserverDaemon(cfg=cfg)
        assert daemon._scan_test_results() == []

    def test_absent_results_file_returns_empty(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        daemon = ObserverDaemon(cfg=cfg)
        assert daemon._scan_test_results() == []


# ---------------------------------------------------------------------------
# Tests borgnes_map
# ---------------------------------------------------------------------------

class TestBorgnesMap:
    def test_borgnes_map_created_on_rollback_cluster(self, tmp_path):
        """rollback_cluster dans les WAL → borgnes_map.json mis à jour."""
        cfg = _make_cfg(tmp_path)
        wal_dir = Path(cfg["observer"]["wal_dir"])
        wal_dir.mkdir(parents=True)
        entry = {"status": "rolled_back", "error_type": "PatchFailed",
                 "intent": "test stagnation", "files_touched": []}
        for i in range(3):
            (wal_dir / f"tx-{i}.wal").write_text(
                json.dumps(entry), encoding="utf-8"
            )

        daemon = ObserverDaemon(cfg=cfg)
        daemon.run_once()

        borgnes_path = Path(cfg["paths"]["borgnes_map"])
        assert borgnes_path.exists()
        data = json.loads(borgnes_path.read_text("utf-8"))
        assert "borgnes" in data
        assert any(b["error_type"] == "PatchFailed" for b in data["borgnes"])

    def test_borgnes_map_accumulates_entries(self, tmp_path):
        """Deux run_once successifs accumulent les borgnes sans dupliquer."""
        cfg = _make_cfg(tmp_path)
        wal_dir = Path(cfg["observer"]["wal_dir"])
        wal_dir.mkdir(parents=True)
        entry = {"status": "rolled_back", "error_type": "SyntaxError",
                 "intent": "fix", "files_touched": []}
        for i in range(3):
            (wal_dir / f"tx-{i}.wal").write_text(json.dumps(entry), encoding="utf-8")

        daemon = ObserverDaemon(cfg=cfg)
        daemon.run_once()
        daemon.run_once()

        borgnes_path = Path(cfg["paths"]["borgnes_map"])
        data = json.loads(borgnes_path.read_text("utf-8"))
        # Un seul entry SyntaxError, count cumulé
        syntax_entries = [b for b in data["borgnes"] if b["error_type"] == "SyntaxError"]
        assert len(syntax_entries) == 1
        assert syntax_entries[0]["count"] >= 6  # 3 + 3


# ---------------------------------------------------------------------------
# Tests helpers module-level
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_deduplicate_merges_count(self):
        """3 signaux du même pattern → 1 signal avec count=3."""
        signals = [
            _make_signal(pattern="missing_import", source="log", severity="medium"),
            _make_signal(pattern="missing_import", source="log", severity="medium"),
            _make_signal(pattern="missing_import", source="log", severity="medium"),
        ]
        result = _deduplicate(signals)
        assert len(result) == 1
        assert result[0]["count"] == 3

    def test_deduplicate_preserves_different_patterns(self):
        """Signaux de patterns différents sont tous conservés."""
        signals = [
            _make_signal(pattern="coroutine_never_awaited", source="log"),
            _make_signal(pattern="missing_import", source="log"),
            _make_signal(pattern="rollback_cluster", source="wal"),
        ]
        result = _deduplicate(signals)
        assert len(result) == 3

    def test_make_signal_defaults(self):
        sig = _make_signal(pattern="test_pattern", source="log")
        assert sig["pattern"] == "test_pattern"
        assert sig["source"] == "log"
        assert sig["severity"] == "medium"
        assert sig["count"] == 1

    def test_parse_wal_valid_ndjson(self, tmp_path):
        wal_file = tmp_path / "test.wal"
        entries = [
            {"status": "rolled_back", "error_type": "PatchFailed"},
            {"status": "committed"},
        ]
        wal_file.write_text(
            "\n".join(json.dumps(e) for e in entries), encoding="utf-8"
        )
        result = _parse_wal(wal_file)
        assert len(result) == 2
        assert result[0]["status"] == "rolled_back"

    def test_parse_wal_ignores_invalid_lines(self, tmp_path):
        wal_file = tmp_path / "bad.wal"
        wal_file.write_text(
            '{"status": "ok"}\nnot_json_at_all\n{"status": "fail"}\n',
            encoding="utf-8",
        )
        result = _parse_wal(wal_file)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Test TelemetryStore absent → silencieux
# ---------------------------------------------------------------------------

class TestTelemetrySilent:
    def test_telemetry_absent_no_crash(self, tmp_path):
        """Si get_telemetry_history est absent → [] sans exception."""
        cfg = _make_cfg(tmp_path)
        daemon = ObserverDaemon(cfg=cfg)
        # Simulation import absent
        with patch.dict("sys.modules", {"core.llm_generator": None}):
            result = daemon._scan_telemetry()
        assert isinstance(result, list)
