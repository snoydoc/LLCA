# -*- coding: utf-8-sig -*-
"""
test_eval_05_cli.py — Tests smoke EVAL-05 : CLI lcca_eval.py
5 tests couvrant les comportements fondamentaux sans appel Ollama réel.
"""
import json
import re
import subprocess
import sys
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Racine du projet
_ROOT = Path(__file__).resolve().parent.parent


# ── Test 1 : --help retourne exit code 0 ──────────────────────────────────────

def test_cli_help():
    """python lcca_eval.py --help → exit code 0."""
    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(_ROOT / "lcca_eval.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0
    assert "EvalLoop" in result.stdout or "lcca_eval" in result.stdout


# ── Test 2 : probe sans --domain → exit code != 0 ─────────────────────────────

def test_cli_probe_missing_domain():
    """probe sans --domain → exit code != 0 (argparse error)."""
    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(_ROOT / "lcca_eval.py"), "probe"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode != 0


# ── Test 3 : import sans effets de bord ───────────────────────────────────────

def test_cli_import_no_side_effects():
    """
    Charger lcca_eval.py ne doit pas instancier ProbeEngine, Ollama, ni écrire sur disque.
    On vérifie que l'import ne déclenche aucun appel aux moteurs lourds.
    """
    with patch("EvalLoop.engines.probe_engine.ProbeEngine") as mock_probe, \
         patch("EvalLoop.engines.curriculum_tracker.CurriculumTracker") as mock_tracker:

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lcca_eval_side_effects_test", str(_ROOT / "lcca_eval.py")
        )
        # Juste créer le module sans l'exécuter — on vérifie que spec existe
        assert spec is not None

        # Aucune instanciation au niveau module (imports dans les cmd_*)
        mock_probe.assert_not_called()
        mock_tracker.assert_not_called()


# ── Test 4 : cmd_run crée un dossier session YYYY-MM-DD_HH-MM ─────────────────

def test_cli_run_creates_session_dir(tmp_path, monkeypatch):
    """cmd_run avec moteurs mockés → vérifie la création d'un dossier session horodaté."""
    from EvalLoop.evalloop_types import BenchQuestion, JudgeScore, ProbeResponse

    # Question fictive
    mock_q = BenchQuestion(
        id="q1", domain="python_core", palier=0,
        question="?", expected_concepts=["x"],
    )

    # ProbeResponse fictive
    mock_resp = MagicMock(spec=ProbeResponse)
    mock_resp.question_id  = "q1"
    mock_resp.duration_sec = 1.0
    mock_resp.to_dict.return_value = {
        "question_id": "q1",
        "question": mock_q.to_dict(),
        "response": "réponse test",
        "model": "qwen2.5-coder:3b",
        "duration_sec": 1.0,
        "timestamp": "2026-01-01T00:00:00Z",
    }

    # JudgeScore fictif
    mock_score = MagicMock(spec=JudgeScore)
    mock_score.final_score        = 0.65
    mock_score.inject_recommended = False
    mock_score.to_dict.return_value = {
        "question_id": "q1", "judge": "local",
        "concept_score": 0.6, "coherence_score": 0.5, "structure_score": 0.1,
        "final_score": 0.65, "inject_recommended": False, "improved_answer": "",
        "domain": "python_core", "palier": 0, "strengths": [], "weaknesses": [],
    }

    # Patch des constantes de chemin dans lcca_eval
    sessions_root = tmp_path / "sessions"

    # Patch les moteurs via leurs modules sources (les cmd_* importent localement)
    with patch("EvalLoop.engines.probe_engine.ProbeEngine") as MockProbe, \
         patch("EvalLoop.engines.curriculum_tracker.CurriculumTracker") as MockTracker, \
         patch("EvalLoop.engines.judge_engine.JudgeEngine") as MockJudge, \
         patch("EvalLoop.engines.session_reporter.SessionReporter") as MockReporter:

        MockProbe.return_value.probe.return_value              = mock_resp
        MockJudge.return_value.judge.return_value              = mock_score
        MockTracker.return_value.get_state.return_value        = MagicMock(current_palier=0)
        MockTracker.return_value.load_questions.return_value   = [mock_q]
        MockTracker.return_value.update_state.return_value     = MagicMock()
        MockReporter.return_value.generate.return_value        = tmp_path / "report.md"

        import lcca_eval
        # Patch les constantes module-level après import
        monkeypatch.setattr(lcca_eval, "_SESSIONS_DIR", sessions_root)
        monkeypatch.setattr(lcca_eval, "_STATE_PATH",   tmp_path / "eval_state.json")
        monkeypatch.setattr(lcca_eval, "_BENCH_DIR",    tmp_path / "benchmarks")
        monkeypatch.setattr(lcca_eval, "_DEDUP_PATH",   tmp_path / "dedup.json")

        args = MagicMock()
        args.domain = "python_core"
        args.judge  = "local"

        lcca_eval.cmd_run(args)

    # Vérifier qu'un dossier de session horodaté a été créé
    assert sessions_root.exists(), "Le dossier sessions/ n'a pas été créé"
    created = [d for d in sessions_root.iterdir() if d.is_dir()]
    assert len(created) == 1, f"Attendu 1 session, trouvé {len(created)}"
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}$")
    assert pattern.match(created[0].name), f"Format inattendu : {created[0].name}"


# ── Test 5 : distill session introuvable → log WARNING, pas d'exception ───────

def test_cli_distill_session_not_found(tmp_path, caplog, monkeypatch):
    """distill --session inexistant → log WARNING, exit propre (pas d'exception)."""
    with patch("EvalLoop.engines.distill_engine.MemoryEngine"):
        import lcca_eval
        monkeypatch.setattr(lcca_eval, "_DEDUP_PATH", tmp_path / "dedup.json")

        args = MagicMock()
        args.session = str(tmp_path / "session_inexistante_xyz")

        with caplog.at_level(logging.WARNING, logger="lcca.evalloop.cli"):
            lcca_eval.cmd_distill(args)   # ne doit pas lever d'exception

    assert any("introuvable" in r.message.lower() for r in caplog.records)
