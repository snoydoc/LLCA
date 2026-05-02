# -*- coding: utf-8 -*-
"""
Tests SI-03 — OrchestratorLight
Conforme au protocole LCCA : fixtures locales, zéro appel réseau, zéro disque réel.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from SelfImprove.engines.orchestrator import OrchestratorLight, _compare


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path) -> dict:
    """Config minimale pointant sur tmp_path."""
    obs_dir = tmp_path / "observations"
    obs_dir.mkdir()
    return {
        "general": {"coupling_mode": 2},
        "orchestrator": {
            "observation_window": 3,
            "observation_max_age_sec": 600,
            "rules_file": str(tmp_path / "rules.json"),
        },
        "paths": {
            "self_improve_dir": str(tmp_path),
            "observations_dir": str(obs_dir),
            "auto_fixes_dir": str(tmp_path / "auto_fixes"),
            "patterns_dir": str(tmp_path / "patterns"),
            "actions_log": str(tmp_path / "actions.log"),
            "pending_actions": str(tmp_path / "pending_actions.json"),
            "borgnes_map": str(tmp_path / "borgnes_map.json"),
        },
    }


def _write_obs(obs_dir: Path, filename: str, signals: list[dict],
               age_sec: int = 0) -> None:
    """Écrit un fichier observation JSON dans obs_dir."""
    from datetime import datetime, timezone, timedelta
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_sec)
    obs = {
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signals": signals,
    }
    (obs_dir / filename).write_text(json.dumps(obs), encoding="utf-8")


def _write_rules(tmp_path: Path, rules: list[dict]) -> None:
    (tmp_path / "rules.json").write_text(
        json.dumps({"version": "1.0", "rules": rules}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# _compare() — tests unitaires
# ---------------------------------------------------------------------------

class TestCompare:
    def test_eq(self):
        assert _compare(5, "==", 5) is True

    def test_neq(self):
        assert _compare(5, "!=", 3) is True

    def test_gte(self):
        assert _compare(5, ">=", 3) is True
        assert _compare(3, ">=", 3) is True
        assert _compare(2, ">=", 3) is False

    def test_lt(self):
        assert _compare(2, "<", 5) is True
        assert _compare(5, "<", 5) is False

    def test_string_eq(self):
        assert _compare("high", "==", "high") is True
        assert _compare("low", "==", "high") is False

    def test_type_error_returns_false(self):
        assert _compare(None, ">=", 2) is False


# ---------------------------------------------------------------------------
# _eval_condition()
# ---------------------------------------------------------------------------

class TestEvalCondition:
    def _orch(self, tmp_path):
        return OrchestratorLight(dry_run=True, cfg=_make_cfg(tmp_path))

    def test_count_gte_match(self, tmp_path):
        orch = self._orch(tmp_path)
        signals = [{"pattern": "repeated_test_failure", "count": 3, "file": "foo.py"}]
        condition = {
            "field": "signal.count", "operator": ">=", "value": 2,
            "filters": {"pattern": "repeated_test_failure"},
        }
        matched, hits = orch._eval_condition(condition, signals)
        assert matched is True
        assert len(hits) == 1

    def test_count_gte_no_match(self, tmp_path):
        orch = self._orch(tmp_path)
        signals = [{"pattern": "repeated_test_failure", "count": 1, "file": "foo.py"}]
        condition = {
            "field": "signal.count", "operator": ">=", "value": 2,
            "filters": {"pattern": "repeated_test_failure"},
        }
        matched, hits = orch._eval_condition(condition, signals)
        assert matched is False
        assert hits == []

    def test_severity_eq(self, tmp_path):
        orch = self._orch(tmp_path)
        signals = [{"pattern": "crash", "severity": "high", "count": 1}]
        condition = {
            "field": "signal.severity", "operator": "==", "value": "high",
            "filters": {},
        }
        matched, hits = orch._eval_condition(condition, signals)
        assert matched is True

    def test_filter_excludes_non_matching(self, tmp_path):
        orch = self._orch(tmp_path)
        signals = [{"pattern": "other_pattern", "count": 5}]
        condition = {
            "field": "signal.count", "operator": ">=", "value": 1,
            "filters": {"pattern": "coroutine_never_awaited"},
        }
        matched, _ = orch._eval_condition(condition, signals)
        assert matched is False

    def test_unknown_operator(self, tmp_path):
        orch = self._orch(tmp_path)
        signals = [{"pattern": "x", "count": 1}]
        condition = {"field": "signal.count", "operator": "~=", "value": 1, "filters": {}}
        matched, _ = orch._eval_condition(condition, signals)
        assert matched is False


# ---------------------------------------------------------------------------
# run() — dry_run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_no_side_effects(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        _write_obs(Path(cfg["paths"]["observations_dir"]), "obs1.json",
                   [{"pattern": "slow_intent", "count": 2}])
        _write_rules(tmp_path, [{
            "id": "rule_log_slow_intent",
            "condition": {
                "field": "signal.count", "operator": ">=", "value": 1,
                "filters": {"pattern": "slow_intent"},
            },
            "action": "log_only",
            "params": {},
            "require_human_ack": False,
            "cooldown_sec": 1,
            "max_trigger_per_day": 50,
            "min_coupling_mode": 1,
        }])
        orch = OrchestratorLight(dry_run=True, cfg=cfg)
        result = orch.run()

        assert result["triggered"] == 0           # dry_run → jamais triggered
        assert len(result["matched_rules"]) == 1
        assert result["matched_rules"][0]["rule_id"] == "rule_log_slow_intent"
        # Pas de write dans actions.log
        assert not (tmp_path / "actions.log").exists()


# ---------------------------------------------------------------------------
# Cooldown & max_trigger
# ---------------------------------------------------------------------------

class TestCooldown:
    def test_cooldown_blocks_retrigger(self, tmp_path):
        """Deuxième run() dans le même cooldown → règle skippée."""
        from SelfImprove.si_utils import _cooldowns, _trigger_counts, _trigger_date
        # Reset état en mémoire pour isolation
        _cooldowns.clear(); _trigger_counts.clear(); _trigger_date.clear()

        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        _write_obs(obs_dir, "obs1.json", [{"pattern": "slow_intent", "count": 2}])
        rule = {
            "id": "r_cooldown_test",
            "condition": {
                "field": "signal.count", "operator": ">=", "value": 1,
                "filters": {"pattern": "slow_intent"},
            },
            "action": "log_only",
            "params": {},
            "require_human_ack": False,
            "cooldown_sec": 9999,
            "max_trigger_per_day": 50,
            "min_coupling_mode": 1,
        }
        _write_rules(tmp_path, [rule])
        orch = OrchestratorLight(dry_run=False, cfg=cfg)
        r1 = orch.run()
        r2 = orch.run()
        assert r1["triggered"] == 1
        assert r2["triggered"] == 0
        assert r2["skipped"] >= 1

    def test_max_trigger_per_day(self, tmp_path):
        """Après max_trigger_per_day déclenchements, règle skippée."""
        from SelfImprove.si_utils import _cooldowns, _trigger_counts, _trigger_date
        _cooldowns.clear(); _trigger_counts.clear(); _trigger_date.clear()

        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        rule = {
            "id": "r_maxday_test",
            "condition": {
                "field": "signal.count", "operator": ">=", "value": 1,
                "filters": {"pattern": "slow_intent"},
            },
            "action": "log_only",
            "params": {},
            "require_human_ack": False,
            "cooldown_sec": 0,
            "max_trigger_per_day": 2,
            "min_coupling_mode": 1,
        }
        _write_rules(tmp_path, [rule])
        orch = OrchestratorLight(dry_run=False, cfg=cfg)

        triggered = 0
        for i in range(4):
            # Forcer cooldown_sec=0 en remettant last à 0
            from SelfImprove.si_utils import _cooldowns as cd
            cd["r_maxday_test"] = 0.0
            _write_obs(obs_dir, "obs%d.json" % i, [{"pattern": "slow_intent", "count": 2}])
            r = orch.run()
            triggered += r["triggered"]
        assert triggered == 2


# ---------------------------------------------------------------------------
# min_coupling_mode
# ---------------------------------------------------------------------------

class TestCouplingMode:
    def test_min_coupling_mode_skips(self, tmp_path):
        from SelfImprove.si_utils import _cooldowns, _trigger_counts, _trigger_date
        _cooldowns.clear(); _trigger_counts.clear(); _trigger_date.clear()

        cfg = _make_cfg(tmp_path)
        cfg["general"] = {"coupling_mode": 1}
        obs_dir = Path(cfg["paths"]["observations_dir"])
        _write_obs(obs_dir, "obs1.json", [{"pattern": "x", "count": 5}])
        _write_rules(tmp_path, [{
            "id": "r_mode3",
            "condition": {
                "field": "signal.count", "operator": ">=", "value": 1, "filters": {},
            },
            "action": "log_only",
            "params": {},
            "require_human_ack": False,
            "cooldown_sec": 0,
            "max_trigger_per_day": 50,
            "min_coupling_mode": 3,
        }])
        with patch("SelfImprove.engines.orchestrator.get_coupling_mode", return_value=1):
            orch = OrchestratorLight(dry_run=False, cfg=cfg)
            result = orch.run()
        assert result["triggered"] == 0
        assert result["skipped"] >= 1


# ---------------------------------------------------------------------------
# Write-ahead
# ---------------------------------------------------------------------------

class TestWriteAhead:
    def test_write_ahead_before_execute(self, tmp_path):
        """actions.log doit contenir une ligne 'started' avant le statut final."""
        from SelfImprove.si_utils import _cooldowns, _trigger_counts, _trigger_date
        _cooldowns.clear(); _trigger_counts.clear(); _trigger_date.clear()

        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        _write_obs(obs_dir, "obs1.json", [{"pattern": "slow_intent", "count": 2}])
        _write_rules(tmp_path, [{
            "id": "r_wa",
            "condition": {
                "field": "signal.count", "operator": ">=", "value": 1,
                "filters": {"pattern": "slow_intent"},
            },
            "action": "log_only",
            "params": {},
            "require_human_ack": False,
            "cooldown_sec": 0,
            "max_trigger_per_day": 50,
            "min_coupling_mode": 1,
        }])
        orch = OrchestratorLight(dry_run=False, cfg=cfg)
        orch.run()

        log_lines = (tmp_path / "actions.log").read_text(encoding="utf-8")
        assert "started" in log_lines
        assert "success" in log_lines


# ---------------------------------------------------------------------------
# Actions individuelles
# ---------------------------------------------------------------------------

class TestActions:
    def _orch(self, tmp_path):
        from SelfImprove.si_utils import _cooldowns, _trigger_counts, _trigger_date
        _cooldowns.clear(); _trigger_counts.clear(); _trigger_date.clear()
        return OrchestratorLight(dry_run=False, cfg=_make_cfg(tmp_path))

    def test_action_log_only(self, tmp_path):
        orch = self._orch(tmp_path)
        status = orch.execute_action("r1", "log_only", "system", {})
        assert status == "success"

    def test_action_notify_no_ack(self, tmp_path, capsys):
        orch = self._orch(tmp_path)
        signals = [{"pattern": "stagnation_loop", "file": "core/foo.py", "count": 1}]
        status = orch.execute_action(
            "r1", "notify_human", "core/foo.py",
            {"message_template": "Alerte : {pattern} dans {file}"},
            require_ack=False, matching_signals=signals,
        )
        assert status == "success"
        out = capsys.readouterr().out
        assert "Alerte" in out
        assert "stagnation_loop" in out

    def test_action_notify_require_ack(self, tmp_path, capsys):
        orch = self._orch(tmp_path)
        signals = [{"pattern": "crash", "file": "core/bar.py", "count": 1}]
        status = orch.execute_action(
            "r_ack", "notify_human", "core/bar.py",
            {"message_template": "Crash : {pattern}"},
            require_ack=True, matching_signals=signals,
        )
        assert status == "pending_ack"
        # pending_actions.json doit exister
        assert (tmp_path / "pending_actions.json").exists()

    def test_action_trigger_autofix_flag_absent(self, tmp_path):
        orch = self._orch(tmp_path)
        # flag .auto_fix_enabled absent → skipped
        status = orch.execute_action(
            "r_af", "trigger_auto_fix", "system",
            {"pattern_id": "coroutine_never_awaited"},
        )
        assert status == "skipped"

    def test_unknown_action_skipped(self, tmp_path):
        orch = self._orch(tmp_path)
        status = orch.execute_action("r_x", "non_existent_action", "system", {})
        assert status == "skipped"

    def test_failed_action_forces_cooldown(self, tmp_path):
        """Une action échouée doit forcer le cooldown sur la règle."""
        from SelfImprove.si_utils import _cooldowns
        _cooldowns.clear()

        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        _write_obs(obs_dir, "obs1.json", [{"pattern": "slow_intent", "count": 2}])
        _write_rules(tmp_path, [{
            "id": "r_fail",
            "condition": {
                "field": "signal.count", "operator": ">=", "value": 1,
                "filters": {"pattern": "slow_intent"},
            },
            "action": "notify_human",
            "params": {},
            "require_human_ack": False,
            "cooldown_sec": 9999,
            "max_trigger_per_day": 50,
            "min_coupling_mode": 1,
        }])
        orch = OrchestratorLight(dry_run=False, cfg=cfg)

        # On force execute_action à retourner "failed"
        with patch.object(orch, "execute_action", return_value="failed"):
            r = orch.run()

        assert r["skipped"] >= 1
        # Le cooldown doit être posé
        assert "r_fail" in _cooldowns


# ---------------------------------------------------------------------------
# _load_signals() — fenêtre temporelle
# ---------------------------------------------------------------------------

class TestLoadSignals:
    def test_observation_window(self, tmp_path):
        """Seules les N dernières observations doivent être lues."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        cfg["orchestrator"]["observation_window"] = 2

        _write_obs(obs_dir, "obs_a.json", [{"pattern": "p1", "count": 1}])
        _write_obs(obs_dir, "obs_b.json", [{"pattern": "p2", "count": 1}])
        _write_obs(obs_dir, "obs_c.json", [{"pattern": "p3", "count": 1}])

        orch = OrchestratorLight(dry_run=True, cfg=cfg)
        signals = orch._load_signals()
        # window=2 → 2 fichiers lus au max → 2 patterns au max
        assert len(signals) <= 2

    def test_observation_max_age(self, tmp_path):
        """Observation trop ancienne ignorée."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        cfg["orchestrator"]["observation_max_age_sec"] = 10

        # Observation fraîche
        _write_obs(obs_dir, "obs_fresh.json", [{"pattern": "fresh", "count": 1}], age_sec=0)
        # Observation trop ancienne
        _write_obs(obs_dir, "obs_old.json", [{"pattern": "stale", "count": 1}], age_sec=60)

        orch = OrchestratorLight(dry_run=True, cfg=cfg)
        signals = orch._load_signals()
        patterns = [s["pattern"] for s in signals]
        assert "fresh" in patterns
        assert "stale" not in patterns
