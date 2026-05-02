# -*- coding: utf-8-sig -*-
"""
Tests SI-04 — AutoFixEngine
Sprint SI-04 : 14 tests couvrant toutes les guards + patterns missing_import + rollback.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers de fixture
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path: Path) -> dict:
    """Crée une configuration minimale pointant sur tmp_path."""
    obs_dir = tmp_path / "observations"
    obs_dir.mkdir()
    fixes_dir = tmp_path / "auto_fixes"
    fixes_dir.mkdir()
    return {
        "general": {"coupling_mode": 2},
        "auto_fix": {
            "min_coverage": 0.60,
            "failure_cooldown_sec": 3600,
            "auto_push": False,
        },
        "paths": {
            "self_improve_dir": str(tmp_path),
            "observations_dir": str(obs_dir),
            "auto_fixes_dir": str(fixes_dir),
            "actions_log": str(tmp_path / "actions.log"),
            "pending_actions": str(tmp_path / "pending_actions.json"),
            "borgnes_map": str(tmp_path / "borgnes_map.json"),
        },
        "orchestrator": {
            "observation_window": 3,
            "observation_max_age_sec": 600,
            "rules_file": str(tmp_path / "orchestrator_rules.json"),
        },
    }


def _write_whitelist(tmp_path: Path) -> None:
    """Écrit auto_fix_whitelist.json dans tmp_path."""
    whitelist = {
        "version": "1.0",
        "patterns": [
            {
                "id": "missing_import",
                "tool": "string_template",
                "fix_template": "add_import",
                "allowed_files": ["**/*.py"],
                "description": "Ajoute un import manquant",
            },
            {
                "id": "coroutine_never_awaited",
                "tool": "smartpatcher",
                "fix_template": "add_await",
                "allowed_files": ["core/*.py"],
                "description": "Ajoute await (STUB)",
            },
        ],
    }
    (tmp_path / "auto_fix_whitelist.json").write_text(
        json.dumps(whitelist), encoding="utf-8"
    )


def _write_observation(tmp_path: Path, pattern: str, file_path: str, extra: dict | None = None) -> None:
    """Écrit une observation JSON minimale dans observations/."""
    obs_dir = tmp_path / "observations"
    obs_dir.mkdir(exist_ok=True)
    signal = {"pattern": pattern, "file": file_path, "count": 1, "severity": "medium"}
    if extra:
        signal.update(extra)
    obs = {
        "timestamp": "2026-04-23T10:00:00Z",
        "signals": [signal],
    }
    (obs_dir / "obs_001.json").write_text(json.dumps(obs), encoding="utf-8")


def _make_target_py(tmp_path: Path, name: str = "target.py") -> Path:
    p = tmp_path / name
    p.write_text("# dummy module\n\ndef foo():\n    pass\n", encoding="utf-8-sig")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAutoFixEngine:

    # ------------------------------------------------------------------
    # Guard 1 — flag absent
    # ------------------------------------------------------------------

    def test_flag_absent_returns_skipped(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        engine = AutoFixEngine(cfg=cfg)

        # Flag .auto_fix_enabled absent
        status = engine.run("missing_import")
        assert status == "skipped"

    # ------------------------------------------------------------------
    # Guard 2 — mode couplage < 2
    # ------------------------------------------------------------------

    def test_mode_1_returns_skipped(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        cfg["general"]["coupling_mode"] = 1
        _write_whitelist(tmp_path)
        # Flag présent
        (tmp_path / ".auto_fix_enabled").touch()

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=1):
            engine = AutoFixEngine(cfg=cfg)
            status = engine.run("missing_import")

        assert status == "skipped"

    # ------------------------------------------------------------------
    # Guard 3 — pattern absent de la whitelist
    # ------------------------------------------------------------------

    def test_pattern_not_in_whitelist(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            status = engine.run("unknown_pattern_xyz")

        assert status == "skipped"

    # ------------------------------------------------------------------
    # Guard 4 — fichier hors allowed_files
    # ------------------------------------------------------------------

    def test_file_not_in_allowed_files(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        # Whitelist avec allowed_files restreint à core/*.py
        whitelist = {
            "version": "1.0",
            "patterns": [
                {
                    "id": "missing_import",
                    "tool": "string_template",
                    "fix_template": "add_import",
                    "allowed_files": ["core/*.py"],
                    "description": "restreint",
                }
            ],
        }
        (tmp_path / "auto_fix_whitelist.json").write_text(json.dumps(whitelist), encoding="utf-8")
        (tmp_path / ".auto_fix_enabled").touch()
        _write_observation(tmp_path, "missing_import", "notcore/myfile.py",
                           extra={"module": "os"})

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            status = engine.run("missing_import")

        assert status == "skipped"

    # ------------------------------------------------------------------
    # Guard 5 — coverage < seuil
    # ------------------------------------------------------------------

    def test_coverage_below_threshold_returns_failed(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_py(tmp_path)
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "os"})

        # Écrit coverage.json avec line_rate < 0.60
        cov = {"files": {str(target): {"summary": {"line_rate": 0.30}}}}
        (tmp_path.parent / "coverage.json").write_text(json.dumps(cov), encoding="utf-8")

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            # Patch _check_coverage directement pour utiliser notre fichier
            engine._cfg["paths"]["self_improve_dir"] = str(tmp_path)
            with patch.object(engine, "_check_coverage", return_value=False):
                status = engine.run("missing_import")

        assert status == "failed"

    # ------------------------------------------------------------------
    # Guard 6 — tests non verts avant patch
    # ------------------------------------------------------------------

    def test_pre_patch_tests_failing_returns_skipped(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_py(tmp_path)
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "os"})

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            with patch.object(engine, "_check_coverage", return_value=True):
                with patch.object(engine, "_run_tests", return_value=False):
                    status = engine.run("missing_import")

        assert status == "skipped"

    # ------------------------------------------------------------------
    # Guard 7 — patch > 5 lignes
    # ------------------------------------------------------------------

    def test_patch_too_many_lines_returns_skipped(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_py(tmp_path)
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "os"})

        # _compute_patch retourne 6 lignes ajoutées
        big_content = "import os\n" * 6 + target.read_text(encoding="utf-8-sig")
        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            with patch.object(engine, "_check_coverage", return_value=True):
                with patch.object(engine, "_run_tests", return_value=True):
                    with patch.object(engine, "_compute_patch", return_value=(big_content, 6)):
                        status = engine.run("missing_import")

        assert status == "skipped"

    # ------------------------------------------------------------------
    # Guard 8 — tests non verts après patch → rollback
    # ------------------------------------------------------------------

    def test_post_patch_tests_failing_triggers_rollback(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_py(tmp_path)
        original_content = target.read_text(encoding="utf-8-sig")
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "os"})

        patched_content = "import os\n" + original_content

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            with patch.object(engine, "_check_coverage", return_value=True):
                # Avant=True, Après=False
                run_tests_calls = [True, False]
                with patch.object(engine, "_run_tests", side_effect=run_tests_calls):
                    with patch.object(engine, "_compute_patch",
                                      return_value=(patched_content, 1)):
                        with patch.object(engine, "_git_commit"):
                            status = engine.run("missing_import")

        assert status == "failed"
        # Vérification rollback : fichier restauré
        assert target.read_text(encoding="utf-8-sig") == original_content

    # ------------------------------------------------------------------
    # missing_import : import ajouté
    # ------------------------------------------------------------------

    def test_missing_import_fix_adds_import(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_py(tmp_path)
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "os"})

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            with patch.object(engine, "_check_coverage", return_value=True):
                with patch.object(engine, "_run_tests", return_value=True):
                    with patch.object(engine, "_git_commit"):
                        status = engine.run("missing_import")

        assert status == "success"
        content = target.read_text(encoding="utf-8-sig")
        assert "import os" in content

    # ------------------------------------------------------------------
    # missing_import : pas de doublon
    # ------------------------------------------------------------------

    def test_missing_import_no_duplicate(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()

        # Fichier qui contient DÉJÀ l'import
        target = tmp_path / "target.py"
        target.write_text("import os\n\ndef foo():\n    pass\n", encoding="utf-8-sig")
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "os"})

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            with patch.object(engine, "_check_coverage", return_value=True):
                with patch.object(engine, "_run_tests", return_value=True):
                    with patch.object(engine, "_git_commit"):
                        # Patch _compute_patch pour simuler 0 ligne ajoutée (doublon détecté)
                        original = target.read_text(encoding="utf-8-sig")
                        with patch.object(engine, "_compute_patch",
                                          return_value=(original, 0)):
                            status = engine.run("missing_import")

        # 0 lignes ajoutées → patch_lines=0 → success sans modification
        assert status == "success"
        assert target.read_text(encoding="utf-8-sig").count("import os") == 1

    # ------------------------------------------------------------------
    # Succès : fichier patch créé
    # ------------------------------------------------------------------

    def test_success_creates_patch_file(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_py(tmp_path)
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "pathlib"})

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            with patch.object(engine, "_check_coverage", return_value=True):
                with patch.object(engine, "_run_tests", return_value=True):
                    with patch.object(engine, "_git_commit"):
                        status = engine.run("missing_import")

        assert status == "success"
        fixes_dir = tmp_path / "auto_fixes"
        patch_files = list(fixes_dir.glob("missing_import_*.patch"))
        assert len(patch_files) >= 1

    # ------------------------------------------------------------------
    # Succès : log actions.log écrit
    # ------------------------------------------------------------------

    def test_success_writes_auto_fix_success_log(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_py(tmp_path)
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "sys"})

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            with patch.object(engine, "_check_coverage", return_value=True):
                with patch.object(engine, "_run_tests", return_value=True):
                    with patch.object(engine, "_git_commit"):
                        status = engine.run("missing_import")

        assert status == "success"
        log_file = tmp_path / "actions.log"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "missing_import" in content
        assert "success" in content

    # ------------------------------------------------------------------
    # Rollback : fichier restauré
    # ------------------------------------------------------------------

    def test_rollback_restores_file(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_py(tmp_path)
        original = target.read_text(encoding="utf-8-sig")
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "glob"})

        patched = "import glob\n" + original

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            with patch.object(engine, "_check_coverage", return_value=True):
                with patch.object(engine, "_run_tests", side_effect=[True, False]):
                    with patch.object(engine, "_compute_patch",
                                      return_value=(patched, 1)):
                        with patch.object(engine, "_git_commit"):
                            status = engine.run("missing_import")

        assert status == "failed"
        assert target.read_text(encoding="utf-8-sig") == original

    # ------------------------------------------------------------------
    # auto_push jamais appelé
    # ------------------------------------------------------------------

    def test_auto_push_never_called(self, tmp_path):
        from SelfImprove.engines.auto_fix import AutoFixEngine

        cfg = _make_cfg(tmp_path)
        _write_whitelist(tmp_path)
        (tmp_path / ".auto_fix_enabled").touch()
        target = _make_target_py(tmp_path)
        _write_observation(tmp_path, "missing_import", str(target),
                           extra={"module": "re"})

        git_calls: list[list] = []

        def fake_run(cmd, **kwargs):
            git_calls.append(cmd)
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("SelfImprove.engines.auto_fix.get_coupling_mode", return_value=2):
            engine = AutoFixEngine(cfg=cfg)
            with patch.object(engine, "_check_coverage", return_value=True):
                with patch.object(engine, "_run_tests", return_value=True):
                    with patch("SelfImprove.engines.auto_fix.subprocess.run",
                               side_effect=fake_run):
                        engine.run("missing_import")

        # Aucun appel git push dans les commandes
        for cmd in git_calls:
            assert "push" not in cmd, "git push ne doit JAMAIS être appelé"
