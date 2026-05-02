# -*- coding: utf-8-sig -*-
"""
test_eval_03_curriculum.py -- Tests EVAL-03 : CurriculumTracker
10 tests couvrant la gestion d'etat, les paliers et le chargement des questions.
Tous les tests utilisent tmp_path (isolation totale, pas de fichier global).
"""
import json
import pytest
from pathlib import Path

from EvalLoop.engines.curriculum_tracker import CurriculumTracker
from EvalLoop.evalloop_types import BenchQuestion, PalierState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tracker(tmp_path: Path, config: dict = None) -> CurriculumTracker:
    """Cree un CurriculumTracker isole avec tmp_path."""
    state_file     = tmp_path / "eval_state.json"
    benchmarks_dir = tmp_path / "benchmarks"
    benchmarks_dir.mkdir(parents=True, exist_ok=True)
    cfg = config or {
        "scoring": {"unlock_threshold": 0.70},
        "sys02_retrograde": {"retrograde_enabled": False},
    }
    return CurriculumTracker(
        state_path     = state_file,
        benchmarks_dir = benchmarks_dir,
        config         = cfg,
    )


def _seed_questions(tmp_path: Path, domain: str, palier: int, questions: list) -> None:
    """Ecrit un fichier palier_N.json dans benchmarks/<domain>/."""
    domain_dir = tmp_path / "benchmarks" / domain
    domain_dir.mkdir(parents=True, exist_ok=True)
    path = domain_dir / f"palier_{palier}.json"
    path.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")


def _make_question_entry(qid: str, domain: str, palier: int, status: str = "active") -> dict:
    return {
        "id": qid,
        "domain": domain,
        "palier": palier,
        "question": f"Question {qid} ?",
        "expected_concepts": ["concept"],
        "rubric": "",
        "status": status,
        "tags": [],
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_curriculum_initial_state(tmp_path):
    """Domaine inconnu -> PalierState par defaut (palier=0, avg=0.0)."""
    tracker = _make_tracker(tmp_path)
    state   = tracker.get_state("python_core")
    assert isinstance(state, PalierState)
    assert state.current_palier == 0
    assert state.avg_score == 0.0
    assert state.questions_done == 0
    assert state.recent_scores == []


def test_curriculum_update_score(tmp_path):
    """update_state() incremente questions_done et met a jour avg_score."""
    tracker = _make_tracker(tmp_path)
    state   = tracker.update_state("python_core", 0.60)
    assert state.questions_done == 1
    assert abs(state.avg_score - 0.60) < 1e-9


def test_curriculum_unlock_threshold(tmp_path):
    """Apres plusieurs scores eleves, avg_score >= 0.70 -> palier monte."""
    tracker = _make_tracker(tmp_path)
    # On force une moyenne superieure au seuil en un seul appel
    # (questions_done=0 -> avg = score directement)
    state = tracker.update_state("python_core", 0.90)
    assert state.current_palier == 1
    assert state.avg_score == 0.0   # Reset apres unlock
    assert state.sessions_completed == 1


def test_curriculum_no_unlock_below(tmp_path):
    """Score < 0.70 -> palier reste a 0."""
    tracker = _make_tracker(tmp_path)
    state   = tracker.update_state("python_core", 0.50)
    assert state.current_palier == 0


def test_curriculum_palier_0_always_unlocked(tmp_path):
    """Palier 0 est toujours debloque, meme pour un domaine inconnu."""
    tracker = _make_tracker(tmp_path)
    assert tracker.is_unlocked("python_core", 0) is True
    assert tracker.is_unlocked("domaine_inconnu", 0) is True


def test_curriculum_palier_1_locked(tmp_path):
    """Palier 1 est verrouille si current_palier == 0."""
    tracker = _make_tracker(tmp_path)
    assert tracker.is_unlocked("python_core", 1) is False


def test_curriculum_load_questions_active(tmp_path):
    """load_questions() ne retourne que les questions status=='active'."""
    questions = [
        _make_question_entry("q1", "python_core", 0, "active"),
        _make_question_entry("q2", "python_core", 0, "active"),
    ]
    _seed_questions(tmp_path, "python_core", 0, questions)
    tracker = _make_tracker(tmp_path)
    loaded  = tracker.load_questions("python_core", 0)
    assert len(loaded) == 2
    assert all(isinstance(q, BenchQuestion) for q in loaded)
    assert all(q.status == "active" for q in loaded)


def test_curriculum_load_questions_draft(tmp_path):
    """Questions avec status=='draft' sont filtrees."""
    questions = [
        _make_question_entry("q1", "python_core", 0, "active"),
        _make_question_entry("q2", "python_core", 0, "draft"),
        _make_question_entry("q3", "python_core", 0, "draft"),
    ]
    _seed_questions(tmp_path, "python_core", 0, questions)
    tracker = _make_tracker(tmp_path)
    loaded  = tracker.load_questions("python_core", 0)
    assert len(loaded) == 1
    assert loaded[0].id == "q1"


def test_curriculum_atomic_write(tmp_path):
    """eval_state.json est cree apres update_state() et est du JSON valide."""
    tracker    = _make_tracker(tmp_path)
    state_file = tmp_path / "eval_state.json"
    assert not state_file.exists()
    tracker.update_state("python_core", 0.55)
    assert state_file.exists()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "python_core" in data
    assert data["python_core"]["questions_done"] == 1


def test_curriculum_recent_scores_window(tmp_path):
    """recent_scores est limite a 10 entrees (fenetre glissante SYS-02)."""
    tracker = _make_tracker(tmp_path)
    # On insere 12 scores en dessous du seuil d'unlock
    for i in range(12):
        tracker.update_state("python_core", 0.40)
    state = tracker.get_state("python_core")
    assert len(state.recent_scores) <= 10
