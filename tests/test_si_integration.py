# -*- coding: utf-8-sig -*-
"""
Tests SI-07 — Intégration pipeline SelfImprove
Pipeline complet : Observer → Orchestrator → action.
Conforme au protocole LCCA : fixtures locales, zéro appel réseau, zéro disque réel.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from SelfImprove.engines.observer_daemon import ObserverDaemon
from SelfImprove.engines.orchestrator import OrchestratorLight
from SelfImprove.si_utils import (
    _cooldowns,
    _trigger_counts,
    _trigger_date,
)


# ---------------------------------------------------------------------------
# Helpers partagés
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path) -> dict:
    """Config complète pointant sur tmp_path."""
    obs_dir = tmp_path / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auto_fixes").mkdir(exist_ok=True)
    (tmp_path / "patterns").mkdir(exist_ok=True)
    return {
        "general": {"coupling_mode": 2},
        "observer": {
            "interval_sec": 60,
            "wal_dir": str(tmp_path / "transactions"),
            "log_file": str(tmp_path / "lcca.log"),
            "test_results_file": str(tmp_path / "last_results.json"),
            "patterns_file": str(tmp_path / "observer_patterns.json"),
        },
        "orchestrator": {
            "observation_window": 3,
            "observation_max_age_sec": 600,
            "rules_file": str(tmp_path / "orchestrator_rules.json"),
        },
        "auto_fix": {
            "min_coverage": 0.60,
            "failure_cooldown_sec": 3600,
            "auto_push": False,
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


def _write_obs_file(obs_dir: Path, filename: str, signals: list,
                    age_sec: int = 0) -> Path:
    """Écrit un fichier observation JSON horodaté dans obs_dir."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_sec)
    payload = {
        "version": "1.0",
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "signals": signals,
    }
    path = obs_dir / filename
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_rules(rules_file: Path, rules: list) -> None:
    rules_file.write_text(
        json.dumps({"version": "1.0", "rules": rules}, indent=2),
        encoding="utf-8",
    )


def _make_rule(rule_id: str, pattern: str, action: str = "log_only",
               params=None, require_ack: bool = False,
               min_coupling_mode: int = 1, cooldown_sec: int = 0) -> dict:
    return {
        "id": rule_id,
        "condition": {
            "field": "signal.count",
            "operator": ">=",
            "value": 1,
            "filters": {"pattern": pattern},
        },
        "action": action,
        "params": params or {},
        "require_human_ack": require_ack,
        "cooldown_sec": cooldown_sec,
        "max_trigger_per_day": 50,
        "min_coupling_mode": min_coupling_mode,
    }


def _reset_cooldowns() -> None:
    """Vide les dicts module-level pour isolation entre tests."""
    _cooldowns.clear()
    _trigger_counts.clear()
    _trigger_date.clear()


# ---------------------------------------------------------------------------
# Tests pipeline intégration
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    """Pipeline complet Observer -> Orchestrator -> action."""

    def setup_method(self):
        _reset_cooldowns()

    def test_observe_then_decide_dry_run(self, tmp_path):
        """Observation avec signal -> decide dry_run -> matched_rules non vide."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        rules_file = Path(cfg["orchestrator"]["rules_file"])

        # Observer : log contenant un signal coroutine
        log_file = Path(cfg["observer"]["log_file"])
        log_file.write_text(
            "2026-01-01 ERROR coroutine 'bar' was never awaited\n",
            encoding="utf-8",
        )

        daemon = ObserverDaemon(cfg=cfg)
        obs_path = daemon.run_once()
        assert obs_path is not None and obs_path.exists()

        # Orchestrator : regle qui matche le signal
        _write_rules(rules_file, [
            _make_rule("r_coroutine", "coroutine_never_awaited", cooldown_sec=0),
        ])
        orch = OrchestratorLight(dry_run=True, cfg=cfg)
        result = orch.run()

        assert len(result["matched_rules"]) >= 1
        ids = [r["rule_id"] for r in result["matched_rules"]]
        assert "r_coroutine" in ids

    def test_observe_then_decide_log_only(self, tmp_path):
        """Signal slow_intent -> regle log_only -> actions.log mis a jour."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        rules_file = Path(cfg["orchestrator"]["rules_file"])

        _write_obs_file(obs_dir, "obs_slow.json", [
            {"pattern": "slow_intent", "count": 2, "severity": "medium"},
        ])
        _write_rules(rules_file, [
            _make_rule("r_slow", "slow_intent", action="log_only", cooldown_sec=0),
        ])

        orch = OrchestratorLight(dry_run=False, cfg=cfg)
        result = orch.run()

        assert result["triggered"] == 1
        actions_log = Path(cfg["paths"]["actions_log"])
        assert actions_log.exists()
        content = actions_log.read_text(encoding="utf-8")
        assert "r_slow" in content
        assert "success" in content

    def test_observe_then_notify_no_ack(self, tmp_path, capsys):
        """Signal high severity -> notify_human sans ack -> message affiche."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        rules_file = Path(cfg["orchestrator"]["rules_file"])

        _write_obs_file(obs_dir, "obs_high.json", [
            {"pattern": "rollback_cluster", "count": 5, "severity": "high",
             "file": "core/orchestrator.py"},
        ])
        _write_rules(rules_file, [
            _make_rule(
                "r_notify",
                "rollback_cluster",
                action="notify_human",
                params={"message_template": "Alerte rollback : {pattern} ({count}x)"},
                require_ack=False,
                cooldown_sec=0,
            ),
        ])

        orch = OrchestratorLight(dry_run=False, cfg=cfg)
        result = orch.run()

        assert result["triggered"] == 1
        out = capsys.readouterr().out
        assert "Alerte rollback" in out

    def test_observe_then_notify_require_ack(self, tmp_path):
        """Signal -> notify avec require_ack -> pending_actions.json mis a jour."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        rules_file = Path(cfg["orchestrator"]["rules_file"])

        _write_obs_file(obs_dir, "obs_ack.json", [
            {"pattern": "stagnation_loop", "count": 3, "severity": "high",
             "file": "core/coder_agent.py"},
        ])
        _write_rules(rules_file, [
            _make_rule(
                "r_ack",
                "stagnation_loop",
                action="notify_human",
                params={"message_template": "Stagnation sur {file}"},
                require_ack=True,
                cooldown_sec=0,
            ),
        ])

        orch = OrchestratorLight(dry_run=False, cfg=cfg)
        orch.run()

        pending_path = Path(cfg["paths"]["pending_actions"])
        assert pending_path.exists()
        data = json.loads(pending_path.read_text("utf-8"))
        assert len(data["actions"]) >= 1
        assert data["actions"][0]["status"] == "pending"
        assert data["actions"][0]["rule_id"] == "r_ack"

    def test_approve_then_status_changes(self, tmp_path):
        """add_pending_action -> approve_pending_action -> statut 'approved'."""
        from SelfImprove.si_utils import add_pending_action, approve_pending_action
        cfg = _make_cfg(tmp_path)

        action_id = add_pending_action("r_test", "notify_human", "core/foo.py", {}, cfg=cfg)
        result = approve_pending_action(action_id, cfg=cfg)

        assert result is not None
        assert result["status"] == "approved"
        assert result["action_id"] == action_id

        data = json.loads(
            Path(cfg["paths"]["pending_actions"]).read_text("utf-8")
        )
        entry = next(a for a in data["actions"] if a["action_id"] == action_id)
        assert entry["status"] == "approved"

    def test_observation_window_fusion(self, tmp_path):
        """3 observations, meme pattern -> count fusionne dans Orchestrator."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        cfg["orchestrator"]["observation_window"] = 3

        for i in range(3):
            _write_obs_file(obs_dir, "obs_%02d.json" % i, [
                {"pattern": "missing_import", "count": 2, "severity": "medium"},
            ])

        orch = OrchestratorLight(dry_run=True, cfg=cfg)
        signals = orch._load_signals()

        match = next((s for s in signals if s["pattern"] == "missing_import"), None)
        assert match is not None
        assert match["count"] == 6

    def test_observation_max_age_ignored(self, tmp_path):
        """Observation trop ancienne -> ignoree par Orchestrator."""
        cfg = _make_cfg(tmp_path)
        cfg["orchestrator"]["observation_max_age_sec"] = 10
        obs_dir = Path(cfg["paths"]["observations_dir"])

        _write_obs_file(obs_dir, "obs_fresh.json",
                        [{"pattern": "slow_intent", "count": 2}], age_sec=0)
        _write_obs_file(obs_dir, "obs_stale.json",
                        [{"pattern": "stale_pattern", "count": 5}], age_sec=120)

        orch = OrchestratorLight(dry_run=True, cfg=cfg)
        signals = orch._load_signals()

        patterns = [s["pattern"] for s in signals]
        assert "slow_intent" in patterns
        assert "stale_pattern" not in patterns

    def test_cooldown_prevents_retrigger(self, tmp_path):
        """Regle declenchee -> cooldown -> deuxieme run -> skipped."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        rules_file = Path(cfg["orchestrator"]["rules_file"])

        _write_obs_file(obs_dir, "obs1.json", [
            {"pattern": "slow_intent", "count": 2, "severity": "medium"},
        ])
        _write_rules(rules_file, [
            _make_rule("r_cd", "slow_intent", cooldown_sec=9999),
        ])

        orch = OrchestratorLight(dry_run=False, cfg=cfg)
        r1 = orch.run()
        r2 = orch.run()

        assert r1["triggered"] == 1
        assert r2["triggered"] == 0
        assert r2["skipped"] >= 1

    def test_max_trigger_per_day(self, tmp_path):
        """Regle declenchee max_trigger_per_day fois -> bloquee ensuite."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        rules_file = Path(cfg["orchestrator"]["rules_file"])

        _write_rules(rules_file, [{
            "id": "r_maxday",
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
        }])

        orch = OrchestratorLight(dry_run=False, cfg=cfg)
        triggered = 0
        for i in range(5):
            _cooldowns["r_maxday"] = 0.0  # reset cooldown, pas le compteur jour
            _write_obs_file(obs_dir, "obs_%d.json" % i, [
                {"pattern": "slow_intent", "count": 2},
            ])
            r = orch.run()
            triggered += r["triggered"]

        assert triggered == 2

    def test_mode_1_blocks_min_coupling_mode_2_rule(self, tmp_path):
        """Mode 1 -> regle avec min_coupling_mode=2 ignoree."""
        cfg = _make_cfg(tmp_path)
        cfg["general"]["coupling_mode"] = 1
        obs_dir = Path(cfg["paths"]["observations_dir"])
        rules_file = Path(cfg["orchestrator"]["rules_file"])

        _write_obs_file(obs_dir, "obs1.json", [
            {"pattern": "slow_intent", "count": 3},
        ])
        _write_rules(rules_file, [
            _make_rule("r_mode2", "slow_intent",
                       action="log_only", min_coupling_mode=2),
        ])

        with patch(
            "SelfImprove.engines.orchestrator.get_coupling_mode", return_value=1
        ):
            orch = OrchestratorLight(dry_run=False, cfg=cfg)
            result = orch.run()

        assert result["triggered"] == 0
        assert result["skipped"] >= 1

    def test_write_ahead_before_action(self, tmp_path):
        """'started' doit apparaitre dans actions.log avant le statut final."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        rules_file = Path(cfg["orchestrator"]["rules_file"])

        _write_obs_file(obs_dir, "obs1.json", [
            {"pattern": "slow_intent", "count": 1},
        ])
        _write_rules(rules_file, [
            _make_rule("r_wa", "slow_intent", action="log_only", cooldown_sec=0),
        ])

        orch = OrchestratorLight(dry_run=False, cfg=cfg)
        orch.run()

        rows = list(csv.reader(
            Path(cfg["paths"]["actions_log"]).read_text("utf-8").splitlines()
        ))
        statuses = [r[4] for r in rows if len(r) >= 5]
        assert "started" in statuses
        assert "success" in statuses

        # "started" precede "success" dans le fichier
        idx_started = next(i for i, r in enumerate(rows) if len(r) >= 5 and r[4] == "started")
        idx_success = next(i for i, r in enumerate(rows) if len(r) >= 5 and r[4] == "success")
        assert idx_started < idx_success
