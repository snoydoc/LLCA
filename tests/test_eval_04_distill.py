# -*- coding: utf-8-sig -*-
"""
test_eval_04_distill.py — Tests EVAL-04 : DistillEngine + JudgeClaude stub
10 tests couvrant les filtres d'éligibilité, la déduplication, le payload et l'I/O.
MemoryEngine est mocké dans tous les tests (pas d'appel ChromaDB réel).
"""
import hashlib
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from EvalLoop.evalloop_types import JudgeScore


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_engine(tmp_path: Path, mock_mem=None):
    """Crée un DistillEngine avec MemoryEngine mocké via patch du binding local."""
    dedup_path = tmp_path / "eval_dedup_index.json"
    config = {"scoring": {"min_inject_score": 0.70}}

    # Patch le binding local dans distill_engine (là où MemoryEngine est utilisé)
    with patch("EvalLoop.engines.distill_engine.MemoryEngine") as mock_cls:
        mock_result = MagicMock()
        mock_result.stored = True
        mock_result.reason = None
        mock_instance = MagicMock()
        mock_instance.store.return_value = mock_result
        mock_cls.return_value = mock_instance

        from EvalLoop.engines.distill_engine import DistillEngine
        engine = DistillEngine(dedup_path=dedup_path, config=config)

    # Remplace l'instance par le mock fourni si précisé
    if mock_mem is not None:
        engine._mem = mock_mem

    return engine


def _make_eligible_score(**kwargs) -> JudgeScore:
    """JudgeScore éligible par défaut (judge=claude, inject=True, score=0.75)."""
    defaults = dict(
        question_id        = "python_core/p0/q1",
        judge              = "claude",
        concept_score      = 0.8,
        coherence_score    = 0.7,
        structure_score    = 0.3,
        final_score        = 0.75,
        inject_recommended = True,
        improved_answer    = "Une réponse améliorée suffisamment longue.",
        domain             = "python_core",
        palier             = 0,
    )
    defaults.update(kwargs)
    return JudgeScore(**defaults)


def _write_scores(session_dir: Path, scores: list) -> None:
    """Écrit scores.jsonl dans session_dir."""
    session_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(s.to_dict()) for s in scores]
    (session_dir / "scores.jsonl").write_text(
        "\n".join(lines), encoding="utf-8-sig"
    )


# ── Tests filtres ─────────────────────────────────────────────────────────────

def test_distill_skips_local_judge(tmp_path):
    """score.judge='local' → _is_eligible() == False (toujours)."""
    engine = _make_engine(tmp_path)
    score  = _make_eligible_score(judge="local", inject_recommended=False, improved_answer="")
    assert engine._is_eligible(score) is False


def test_distill_skips_inject_false(tmp_path):
    """inject_recommended=False → _is_eligible() == False."""
    engine = _make_engine(tmp_path)
    score  = _make_eligible_score(inject_recommended=False)
    assert engine._is_eligible(score) is False


def test_distill_skips_low_score(tmp_path):
    """final_score=0.65 (< 0.70) → _is_eligible() == False."""
    engine = _make_engine(tmp_path)
    score  = _make_eligible_score(final_score=0.65)
    assert engine._is_eligible(score) is False


def test_distill_skips_empty_answer(tmp_path):
    """improved_answer='' ou '   ' → _is_eligible() == False."""
    engine = _make_engine(tmp_path)
    assert engine._is_eligible(_make_eligible_score(improved_answer="")) is False
    assert engine._is_eligible(_make_eligible_score(improved_answer="   ")) is False


def test_distill_eligible_claude(tmp_path):
    """judge=claude, inject=True, score=0.75, answer='...' → _is_eligible() == True."""
    engine = _make_engine(tmp_path)
    score  = _make_eligible_score()
    assert engine._is_eligible(score) is True


# ── Tests déduplication ───────────────────────────────────────────────────────

def test_distill_dedup_second_run(tmp_path):
    """Même improved_answer deux fois → deuxième distill() retourne 0."""
    engine  = _make_engine(tmp_path)
    session = tmp_path / "session"
    score   = _make_eligible_score()
    _write_scores(session, [score])

    first  = engine.distill(session)
    second = engine.distill(session)

    assert first  == 1
    assert second == 0


def test_distill_dedup_uses_set(tmp_path):
    """_load_dedup_index() retourne un set (pas une liste)."""
    engine = _make_engine(tmp_path)
    result = engine._load_dedup_index()
    assert isinstance(result, set)


# ── Tests payload ─────────────────────────────────────────────────────────────

def test_distill_payload_content_key(tmp_path):
    """_build_payload() → 'content' présent, clés interdites absentes."""
    engine  = _make_engine(tmp_path)
    score   = _make_eligible_score()
    payload = engine._build_payload(score, "abc123")

    assert "content" in payload
    assert payload["content"] == score.improved_answer

    # Clés interdites (extract_content() les prendrait en priorité sur "content")
    for forbidden in ("code", "snippet", "error", "text"):
        assert forbidden not in payload, f"Clé interdite présente : {forbidden}"


# ── Tests I/O pattern ─────────────────────────────────────────────────────────

def test_distill_single_write(tmp_path):
    """5 entrées éligibles distinctes → _save_dedup_index() appelé une seule fois."""
    engine  = _make_engine(tmp_path)
    session = tmp_path / "session"

    scores = [
        _make_eligible_score(
            question_id    = f"q{i}",
            improved_answer = f"Réponse unique numéro {i} avec assez de contenu.",
        )
        for i in range(5)
    ]
    _write_scores(session, scores)

    save_count    = 0
    original_save = engine._save_dedup_index

    def counting_save(index):
        nonlocal save_count
        save_count += 1
        original_save(index)

    engine._save_dedup_index = counting_save
    injected = engine.distill(session)

    assert injected   == 5
    assert save_count == 1   # UNE SEULE écriture, pas 5


# ── Tests intégration (mocké) ─────────────────────────────────────────────────

def test_distill_calls_memory_store(tmp_path):
    """MemoryEngine.store mocké → vérifie appel avec collection='lcca_context'."""
    mock_result        = MagicMock()
    mock_result.stored = True
    mock_result.reason = None
    mock_mem           = MagicMock()
    mock_mem.store.return_value = mock_result

    engine  = _make_engine(tmp_path, mock_mem=mock_mem)
    session = tmp_path / "session"
    score   = _make_eligible_score()
    _write_scores(session, [score])

    injected = engine.distill(session)

    assert injected == 1
    mock_mem.store.assert_called_once()
    call_args = mock_mem.store.call_args
    # Premier argument positionnel = collection
    assert call_args[0][0] == "lcca_context"
    # Payload contient "content"
    payload = call_args[0][1]
    assert payload["content"] == score.improved_answer
