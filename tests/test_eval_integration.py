# -*- coding: utf-8-sig -*-
"""
test_eval_integration.py -- INT-01
5 tests bout-en-bout validant les contrats entre composants EvalLoop.
MemoryEngine toujours mocke -- zero appel reseau ou ChromaDB reel.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from EvalLoop.evalloop_types import (
    BenchQuestion, ProbeResponse, JudgeScore, PalierState,
)
from EvalLoop.judges.judge_local import JudgeLocal
from EvalLoop.engines.curriculum_tracker import CurriculumTracker


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session_dir(tmp_path: Path, name: str = "2026-04-24_14-30") -> Path:
    """Cree une structure session minimale."""
    session = tmp_path / "sessions" / name
    session.mkdir(parents=True, exist_ok=True)
    return session


def _make_config(tmp_path: Path) -> dict:
    """Config minimale sans dependance a eval_config.toml."""
    return {
        "scoring": {
            "min_inject_score": 0.70,
            "unlock_threshold": 0.70,
            "gatekeeper_min":   0.30,
        },
        "sessions": {
            "sessions_dir": str(tmp_path / "sessions"),
            "state_file":   str(tmp_path / "eval_state.json"),
            "dedup_index":  str(tmp_path / "eval_dedup_index.json"),
        },
        "storage": {"collection": "lcca_context"},
        "sys02_retrograde": {"retrograde_enabled": False},
    }


def _make_question() -> BenchQuestion:
    return BenchQuestion(
        id                = "python_core/p0/gil_001",
        domain            = "python_core",
        palier            = 0,
        question          = "Qu'est-ce que le GIL ?",
        expected_concepts = ["GIL", "thread", "CPython"],
    )


def _make_good_response(question: BenchQuestion) -> ProbeResponse:
    return ProbeResponse(
        question_id  = question.id,
        question     = question,
        response     = (
            "Le GIL (Global Interpreter Lock) protege l'interpreteur CPython. "
            "Il empeche plusieurs thread d'executer du bytecode simultanement."
        ),
        model        = "qwen2.5-coder:3b",
        duration_sec = 8.4,
        timestamp    = "2026-04-24T14:30:00Z",
    )


# ── Test 1 -- probe -> judge_local -> scores.jsonl ────────────────────────────

def test_pipeline_probe_to_scores(tmp_path):
    """
    ProbeResponse (construite) -> JudgeLocal (reel) -> scores.jsonl ecrit et relu.
    Valide le contrat ProbeResponse -> JudgeScore -> serialisation JSONL.
    """
    question  = _make_question()
    response  = _make_good_response(question)
    session   = _make_session_dir(tmp_path)

    judge = JudgeLocal()
    score = judge.score(question, response)

    # Ecriture JSONL
    responses_path = session / "responses.jsonl"
    scores_path    = session / "scores.jsonl"
    responses_path.write_text(
        json.dumps(response.to_dict()) + "\n", encoding="utf-8-sig"
    )
    scores_path.write_text(
        json.dumps(score.to_dict()) + "\n", encoding="utf-8-sig"
    )

    # Relecture et assertions
    loaded = JudgeScore(**json.loads(scores_path.read_text(encoding="utf-8-sig").strip()))
    assert loaded.judge              == "local"
    assert loaded.inject_recommended is False   # INVARIANT JudgeLocal
    assert loaded.improved_answer    == ""       # INVARIANT JudgeLocal
    assert 0.0 <= loaded.final_score <= 1.0
    assert loaded.question_id == question.id


# ── Test 2 -- distill avec JudgeClaude stub ───────────────────────────────────

def test_pipeline_distill_claude(tmp_path):
    """
    scores.jsonl avec 1 entree JudgeClaude eligible -> DistillEngine injecte 1.
    MemoryEngine mocke -- valide le payload et le contrat store().
    """
    from core.memory_engine_store import StoreResult

    config      = _make_config(tmp_path)
    session_dir = _make_session_dir(tmp_path)

    score = JudgeScore(
        question_id        = "python_core/p0/gil_001",
        judge              = "claude",
        final_score        = 0.82,
        inject_recommended = True,
        improved_answer    = "Le GIL est un verrou global de CPython qui serialise les threads.",
        domain             = "python_core",
        palier             = 0,
    )
    (session_dir / "scores.jsonl").write_text(
        json.dumps(score.to_dict()) + "\n", encoding="utf-8-sig"
    )

    with patch("EvalLoop.engines.distill_engine.MemoryEngine") as MockMem:
        MockMem.return_value.store.return_value = StoreResult(
            stored=True, collection="lcca_context", entry_id="abc123"
        )
        from EvalLoop.engines.distill_engine import DistillEngine
        engine   = DistillEngine(
            dedup_path = Path(config["sessions"]["dedup_index"]),
            config     = config,
        )
        injected = engine.distill(session_dir)

    assert injected == 1
    MockMem.return_value.store.assert_called_once()
    call_args = MockMem.return_value.store.call_args
    assert call_args[0][0] == "lcca_context"
    payload = call_args[0][1]
    assert "content"  in payload
    assert "code"     not in payload
    assert "snippet"  not in payload
    assert "error"    not in payload
    assert "text"     not in payload


# ── Test 3 -- curriculum update apres session ─────────────────────────────────

def test_pipeline_curriculum_update(tmp_path):
    """
    CurriculumTracker.update_state() apres 5 scores -> eval_state.json mis a jour.
    Valide la persistance et le calcul de avg_score.
    """
    config  = _make_config(tmp_path)
    tracker = CurriculumTracker(
        state_path     = Path(config["sessions"]["state_file"]),
        benchmarks_dir = tmp_path / "benchmarks",
        config         = config,
    )

    scores = [0.65, 0.60, 0.62, 0.58, 0.63]   # Tous < 0.70 : palier reste 0
    for s in scores:
        tracker.update_state("python_core", s)

    state = tracker.get_state("python_core")
    assert state.questions_done == 5
    expected_avg = sum(scores) / len(scores)
    assert abs(state.avg_score - expected_avg) < 0.01
    assert state.current_palier == 0   # Moyenne < 0.70 -> pas de montee


# ── Test 4 -- dedup cross-session ─────────────────────────────────────────────

def test_pipeline_dedup_cross_session(tmp_path):
    """
    Meme improved_answer dans deux sessions differentes -> deuxieme distill() retourne 0.
    Valide que eval_dedup_index.json persiste correctement entre deux appels.
    """
    from core.memory_engine_store import StoreResult

    config   = _make_config(tmp_path)
    session1 = _make_session_dir(tmp_path, "2026-04-24_14-30")
    session2 = _make_session_dir(tmp_path, "2026-04-25_10-00")

    same_answer = "Le GIL est un verrou global de CPython qui serialise les threads Python."
    score = JudgeScore(
        question_id        = "python_core/p0/gil_001",
        judge              = "claude",
        final_score        = 0.80,
        inject_recommended = True,
        improved_answer    = same_answer,
        domain             = "python_core",
        palier             = 0,
    )
    for s_dir in [session1, session2]:
        (s_dir / "scores.jsonl").write_text(
            json.dumps(score.to_dict()) + "\n", encoding="utf-8-sig"
        )

    with patch("EvalLoop.engines.distill_engine.MemoryEngine") as MockMem:
        MockMem.return_value.store.return_value = StoreResult(
            stored=True, collection="lcca_context", entry_id="x"
        )
        from EvalLoop.engines.distill_engine import DistillEngine
        engine = DistillEngine(Path(config["sessions"]["dedup_index"]), config)

        first  = engine.distill(session1)
        second = engine.distill(session2)

    assert first  == 1   # Premiere fois : injecte
    assert second == 0   # Meme hash : ignore (dedup cross-session)


# ── Test 5 -- invariant JudgeLocal jamais injecte ────────────────────────────

def test_pipeline_judge_local_never_in_distill(tmp_path):
    """
    scores.jsonl avec uniquement des entrees JudgeLocal -> DistillEngine injecte 0.
    Meme avec final_score=0.99, JudgeLocal n'est jamais eligible a l'injection.
    """
    config      = _make_config(tmp_path)
    session_dir = _make_session_dir(tmp_path)

    # Score local parfait -- invariant : jamais injecte
    score = JudgeScore(
        question_id        = "python_core/p0/gil_001",
        judge              = "local",
        final_score        = 0.99,
        inject_recommended = False,
        improved_answer    = "",
        domain             = "python_core",
        palier             = 0,
    )
    (session_dir / "scores.jsonl").write_text(
        json.dumps(score.to_dict()) + "\n", encoding="utf-8-sig"
    )

    with patch("EvalLoop.engines.distill_engine.MemoryEngine"):
        from EvalLoop.engines.distill_engine import DistillEngine
        engine   = DistillEngine(Path(config["sessions"]["dedup_index"]), config)
        injected = engine.distill(session_dir)

    assert injected == 0   # INVARIANT : JudgeLocal n'injecte jamais, meme a 0.99
