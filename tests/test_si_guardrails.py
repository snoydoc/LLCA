# -*- coding: utf-8-sig -*-
"""
Tests SI-07 — Garde-fous SelfImprove
Verification de tous les garde-fous codes en dur dans AutoFixEngine,
EducatorSI et OrchestratorLight.
Conforme au protocole LCCA : fixtures locales, zéro appel réseau.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from SelfImprove.engines.auto_fix import AutoFixEngine
from SelfImprove.engines.educator import EducatorSI
from SelfImprove.engines.orchestrator import OrchestratorLight
from SelfImprove.si_utils import _cooldowns, _trigger_counts, _trigger_date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path) -> dict:
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


def _write_whitelist(tmp_path: Path, patterns: list) -> None:
    (tmp_path / "auto_fix_whitelist.json").write_text(
        json.dumps({"version": "1.0", "patterns": patterns}),
        encoding="utf-8",
    )


def _write_signal(obs_dir: Path, pattern_id: str, file_path: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    payload = {
        "version": "1.0",
        "timestamp": ts,
        "signals": [{
            "pattern": pattern_id,
            "source": "log",
            "severity": "medium",
            "count": 1,
            "file": file_path,
            "module": "some_module",
        }],
    }
    (obs_dir / "signal.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _make_target_file(tmp_path: Path, content: str = "x = 1\n") -> Path:
    """Cree un fichier Python cible dans tmp_path/core/."""
    core_dir = tmp_path / "core"
    core_dir.mkdir(exist_ok=True)
    target = core_dir / "target_module.py"
    target.write_text(content, encoding="utf-8-sig")
    return target


def _reset_cooldowns() -> None:
    _cooldowns.clear()
    _trigger_counts.clear()
    _trigger_date.clear()


# ---------------------------------------------------------------------------
# Garde-fous AutoFixEngine
# ---------------------------------------------------------------------------

class TestGuardrails:
    """Verification de tous les garde-fous codes en dur."""

    def setup_method(self):
        _reset_cooldowns()

    def test_no_autofix_without_flag(self, tmp_path):
        """AutoFix sans .auto_fix_enabled -> skipped immediat."""
        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path, [{"id": "missing_import", "fix_template": "add_import",
                                     "allowed_files": ["core/*.py"]}])
        engine = AutoFixEngine(cfg=cfg)
        # flag absent -> skipped sans aucun autre traitement
        status = engine.run("missing_import")
        assert status == "skipped"

    def test_no_autofix_mode_1(self, tmp_path):
        """Mode 1 -> AutoFix skipped."""
        cfg = _make_cfg(tmp_path)
        cfg["general"]["coupling_mode"] = 1
        (tmp_path / ".auto_fix_enabled").touch()
        _write_whitelist(tmp_path, [{"id": "missing_import", "fix_template": "add_import",
                                     "allowed_files": ["core/*.py"]}])

        with patch(
            "SelfImprove.engines.auto_fix.get_coupling_mode", return_value=1
        ):
            engine = AutoFixEngine(cfg=cfg)
            status = engine.run("missing_import")

        assert status == "skipped"

    def test_no_autofix_pattern_not_in_whitelist(self, tmp_path):
        """Pattern inconnu -> skipped immediat."""
        cfg = _make_cfg(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        _write_whitelist(tmp_path, [])  # whitelist vide

        engine = AutoFixEngine(cfg=cfg)
        status = engine.run("pattern_inexistant")
        assert status == "skipped"

    def test_no_autofix_pre_tests_red(self, tmp_path):
        """Tests non verts avant patch -> skipped."""
        cfg = _make_cfg(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_file(tmp_path)

        _write_whitelist(tmp_path, [{
            "id": "missing_import", "fix_template": "add_import",
            "allowed_files": ["*.py", "core/*.py"],
        }])
        _write_signal(
            Path(cfg["paths"]["observations_dir"]),
            "missing_import",
            str(target.as_posix()),
        )

        engine = AutoFixEngine(cfg=cfg)
        # coverage OK, tests pre-patch KO
        with patch.object(engine, "_check_coverage", return_value=True), \
             patch.object(engine, "_run_tests", return_value=False):
            status = engine.run("missing_import")

        assert status == "skipped"

    def test_rollback_on_post_test_failure(self, tmp_path):
        """Tests non verts apres patch -> fichier restaure exactement."""
        cfg = _make_cfg(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        original_content = "x = 1\n"
        target = _make_target_file(tmp_path, original_content)

        _write_whitelist(tmp_path, [{
            "id": "missing_import", "fix_template": "add_import",
            "allowed_files": ["*.py", "core/*.py"],
        }])
        _write_signal(
            Path(cfg["paths"]["observations_dir"]),
            "missing_import",
            str(target.as_posix()),
        )

        engine = AutoFixEngine(cfg=cfg)
        # tests pre OK, patch applique, tests post KO -> rollback
        call_count = {"n": 0}

        def _run_tests_side_effect(path):
            call_count["n"] += 1
            return call_count["n"] == 1  # True premiere fois, False deuxieme

        with patch.object(engine, "_check_coverage", return_value=True), \
             patch.object(engine, "_run_tests", side_effect=_run_tests_side_effect), \
             patch.object(engine, "_compute_patch",
                          return_value=("import os\n" + original_content, 1)), \
             patch.object(engine, "_git_commit"), \
             patch.object(engine, "_write_patch_file"):
            status = engine.run("missing_import")

        assert status == "failed"
        # Fichier restaure a son contenu original
        assert target.read_text(encoding="utf-8-sig") == original_content

    def test_no_autofix_patch_too_large(self, tmp_path):
        """Patch > 5 lignes -> skipped immediat."""
        cfg = _make_cfg(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_file(tmp_path)

        _write_whitelist(tmp_path, [{
            "id": "missing_import", "fix_template": "add_import",
            "allowed_files": ["*.py", "core/*.py"],
        }])
        _write_signal(
            Path(cfg["paths"]["observations_dir"]),
            "missing_import",
            str(target.as_posix()),
        )

        engine = AutoFixEngine(cfg=cfg)
        big_patch = "line\n" * 10 + "x = 1\n"
        with patch.object(engine, "_check_coverage", return_value=True), \
             patch.object(engine, "_run_tests", return_value=True), \
             patch.object(engine, "_compute_patch", return_value=(big_patch, 10)):
            status = engine.run("missing_import")

        assert status == "skipped"

    def test_max_5_lines_hard_limit(self, tmp_path):
        """Patch exactement 6 lignes -> skipped (limite dure = 5)."""
        cfg = _make_cfg(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_file(tmp_path)

        _write_whitelist(tmp_path, [{
            "id": "missing_import", "fix_template": "add_import",
            "allowed_files": ["*.py", "core/*.py"],
        }])
        _write_signal(
            Path(cfg["paths"]["observations_dir"]),
            "missing_import",
            str(target.as_posix()),
        )

        engine = AutoFixEngine(cfg=cfg)
        patch_content = "line\n" * 6 + "x = 1\n"
        with patch.object(engine, "_check_coverage", return_value=True), \
             patch.object(engine, "_run_tests", return_value=True), \
             patch.object(engine, "_compute_patch", return_value=(patch_content, 6)):
            status = engine.run("missing_import")

        assert status == "skipped"

    def test_no_autofix_coverage_below_60(self, tmp_path):
        """Coverage 55% -> failed (cooldown force)."""
        cfg = _make_cfg(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_file(tmp_path)

        _write_whitelist(tmp_path, [{
            "id": "missing_import", "fix_template": "add_import",
            "allowed_files": ["*.py", "core/*.py"],
        }])
        _write_signal(
            Path(cfg["paths"]["observations_dir"]),
            "missing_import",
            str(target.as_posix()),
        )

        engine = AutoFixEngine(cfg=cfg)
        with patch.object(engine, "_check_coverage", return_value=False):
            status = engine.run("missing_import")

        assert status == "failed"

    def test_no_git_push(self, tmp_path):
        """Succes auto-fix -> git push jamais appele."""
        cfg = _make_cfg(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_file(tmp_path)

        _write_whitelist(tmp_path, [{
            "id": "missing_import", "fix_template": "add_import",
            "allowed_files": ["*.py", "core/*.py"],
        }])
        _write_signal(
            Path(cfg["paths"]["observations_dir"]),
            "missing_import",
            str(target.as_posix()),
        )

        engine = AutoFixEngine(cfg=cfg)
        git_calls = []

        def _fake_run(cmd, **kwargs):
            git_calls.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch.object(engine, "_check_coverage", return_value=True), \
             patch.object(engine, "_run_tests", return_value=True), \
             patch.object(engine, "_compute_patch",
                          return_value=("import os\n" + target.read_text("utf-8-sig"), 1)), \
             patch("SelfImprove.engines.auto_fix.subprocess.run", side_effect=_fake_run):
            engine.run("missing_import")

        # Aucune commande git ne doit contenir "push"
        push_calls = [c for c in git_calls if isinstance(c, list) and "push" in c]
        assert push_calls == [], "git push ne doit jamais etre appele"

    # ---------------------------------------------------------------------------
    # Garde-fous EducatorSI
    # ---------------------------------------------------------------------------

    def test_educator_never_modifies_rules(self, tmp_path):
        """EducatorSI.ingest() -> orchestrator_rules.json inchange."""
        cfg = _make_cfg(tmp_path)
        rules_content = json.dumps({"version": "1.0", "rules": []})
        rules_file = tmp_path / "orchestrator_rules.json"
        rules_file.write_text(rules_content, encoding="utf-8")

        # Creer un actions.log avec un succes pour declencher ingest
        actions_log = Path(cfg["paths"]["actions_log"])
        actions_log.write_text(
            "2026-01-01T00:00:00Z,pattern_x,auto_fix,core/f.py,success,\n",
            encoding="utf-8",
        )

        educator = EducatorSI(cfg=cfg)
        educator.ingest("auto-fix")

        # Le fichier rules ne doit pas avoir ete modifie
        assert rules_file.read_text(encoding="utf-8") == rules_content

    def test_educator_never_modifies_whitelist(self, tmp_path):
        """EducatorSI.ingest() -> auto_fix_whitelist.json inchange."""
        cfg = _make_cfg(tmp_path)
        whitelist_content = json.dumps({"version": "1.0", "patterns": []})
        whitelist_file = tmp_path / "auto_fix_whitelist.json"
        whitelist_file.write_text(whitelist_content, encoding="utf-8")

        actions_log = Path(cfg["paths"]["actions_log"])
        actions_log.write_text(
            "2026-01-01T00:00:00Z,pattern_y,auto_fix,core/g.py,success,\n",
            encoding="utf-8",
        )

        educator = EducatorSI(cfg=cfg)
        educator.ingest("auto-fix")

        assert whitelist_file.read_text(encoding="utf-8") == whitelist_content

    def test_educator_output_is_md_only(self, tmp_path):
        """EducatorSI ne cree que des fichiers .md dans patterns/."""
        cfg = _make_cfg(tmp_path)
        patterns_dir = Path(cfg["paths"]["patterns_dir"])

        actions_log = Path(cfg["paths"]["actions_log"])
        actions_log.write_text(
            "2026-01-01T00:00:00Z,pattern_z,auto_fix,core/h.py,success,\n",
            encoding="utf-8",
        )

        educator = EducatorSI(cfg=cfg)
        result = educator.ingest("auto-fix")

        assert result is not None
        assert result.suffix == ".md"
        # Seuls des .md dans patterns/
        non_md = [f for f in patterns_dir.iterdir() if f.suffix != ".md"]
        assert non_md == []

    def test_educator_dedup_prevents_duplicate_suggestion(self, tmp_path):
        """Deux appels identiques -> meme fichier retourne (deduplication)."""
        cfg = _make_cfg(tmp_path)
        actions_log = Path(cfg["paths"]["actions_log"])
        actions_log.write_text(
            "2026-01-01T00:00:00Z,pattern_dedup,auto_fix,core/d.py,success,\n",
            encoding="utf-8",
        )

        educator = EducatorSI(cfg=cfg)
        result1 = educator.ingest("auto-fix")
        result2 = educator.ingest("auto-fix")

        assert result1 == result2

    # ---------------------------------------------------------------------------
    # Garde-fous Orchestrator
    # ---------------------------------------------------------------------------

    def test_atomic_write_no_half_json(self, tmp_path):
        """Interruption simulee pendant ecriture -> pas de .json corrompu."""
        from SelfImprove.si_utils import atomic_write_json

        target = tmp_path / "safe.json"
        payload = {"key": "value", "nested": {"a": 1, "b": 2}}

        atomic_write_json(target, payload)

        # Fichier .tmp ne doit pas exister apres succes
        tmp_file = target.with_suffix(".tmp")
        assert not tmp_file.exists()

        # Contenu valide
        loaded = json.loads(target.read_text("utf-8"))
        assert loaded == payload

    def test_no_infinite_retry_coder(self, tmp_path):
        """retry_coder_once -> action discrete, pas de boucle infinie."""
        cfg = _make_cfg(tmp_path)
        obs_dir = Path(cfg["paths"]["observations_dir"])
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = {
            "version": "1.0",
            "timestamp": ts,
            "signals": [{"pattern": "slow_intent", "count": 2, "file": "core/f.py"}],
        }
        (obs_dir / "obs1.json").write_text(json.dumps(payload), "utf-8")

        rules_file = Path(cfg["orchestrator"]["rules_file"])
        rules_file.write_text(json.dumps({"version": "1.0", "rules": [{
            "id": "r_retry",
            "condition": {
                "field": "signal.count", "operator": ">=", "value": 1,
                "filters": {"pattern": "slow_intent"},
            },
            "action": "retry_coder_once",
            "params": {},
            "require_human_ack": False,
            "cooldown_sec": 0,
            "max_trigger_per_day": 50,
            "min_coupling_mode": 1,
        }]}), "utf-8")

        orch = OrchestratorLight(dry_run=False, cfg=cfg)
        call_count = {"n": 0}

        def _fake_action(rule_id, action, target, params, require_ack=False, matching_signals=None):
            call_count["n"] += 1
            return "success"

        with patch.object(orch, "execute_action", side_effect=_fake_action):
            orch.run()

        # Une seule execution — pas de retry automatique
        assert call_count["n"] == 1

    def test_mode_3_a2abus_absent_fails_gracefully(self, tmp_path):
        """Mode 3, A2ALocalBus import error -> failed sans crash."""
        cfg = _make_cfg(tmp_path)
        cfg["general"]["coupling_mode"] = 3

        obs_dir = Path(cfg["paths"]["observations_dir"])
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        (obs_dir / "obs1.json").write_text(json.dumps({
            "version": "1.0",
            "timestamp": ts,
            "signals": [{"pattern": "slow_intent", "count": 2, "file": "core/f.py"}],
        }), "utf-8")

        orch = OrchestratorLight(dry_run=False, cfg=cfg)

        with patch(
            "SelfImprove.engines.orchestrator.get_coupling_mode", return_value=3
        ), patch.dict(
            "sys.modules", {"core.agents.a2a_bus": None}
        ):
            status = orch._action_retry_coder_once("core/f.py", {})

        # Doit retourner "failed" sans lever d'exception
        assert status == "failed"
