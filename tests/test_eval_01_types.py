# -*- coding: utf-8-sig -*-
"""
test_eval_01_types.py — Tests EVAL-01 : dataclasses EvalLoop V3
15 tests couvrant les 5 dataclasses + to_dict/from_dict + invariants.
"""
import sys
import pytest

from EvalLoop.evalloop_types import (
    BenchQuestion,
    ProbeResponse,
    JudgeScore,
    DistilledSkill,
    PalierState,
)

_MIN_INJECT_SCORE = 0.70


# ── BenchQuestion ─────────────────────────────────────────────────────────────

def test_bench_question_defaults():
    q = BenchQuestion(
        id="q1", domain="python_core", palier=0,
        question="Qu'est-ce que le GIL ?",
        expected_concepts=["GIL"],
    )
    assert q.status == "active"
    assert q.tags == []
    assert q.rubric == ""


def test_bench_question_to_dict():
    q = BenchQuestion(
        id="q1", domain="python_core", palier=0,
        question="Qu'est-ce que le GIL ?",
        expected_concepts=["GIL", "thread"],
        tags=["concurrence"],
    )
    d = q.to_dict()
    assert d["id"] == "q1"
    assert d["domain"] == "python_core"
    assert d["palier"] == 0
    assert d["expected_concepts"] == ["GIL", "thread"]
    assert d["tags"] == ["concurrence"]
    assert d["status"] == "active"


def test_bench_question_from_dict():
    original = BenchQuestion(
        id="q2", domain="python_core", palier=1,
        question="Expliquez asyncio.",
        expected_concepts=["coroutine", "event loop"],
        rubric="Doit mentionner await.",
        status="active",
        tags=["async"],
    )
    reconstructed = BenchQuestion.from_dict(original.to_dict())
    assert reconstructed.id == original.id
    assert reconstructed.domain == original.domain
    assert reconstructed.palier == original.palier
    assert reconstructed.expected_concepts == original.expected_concepts
    assert reconstructed.status == original.status
    assert reconstructed.tags == original.tags


def test_bench_question_status_draft():
    q = BenchQuestion(
        id="q_draft", domain="python_core", palier=0,
        question="Question en cours de revue.",
        expected_concepts=[],
        status="draft",
    )
    assert q.status == "draft"
    d = q.to_dict()
    assert d["status"] == "draft"
    q2 = BenchQuestion.from_dict(d)
    assert q2.status == "draft"


# ── JudgeScore ────────────────────────────────────────────────────────────────

def test_judge_score_invariant_inject():
    """INVARIANT : JudgeLocal ne decide jamais d'injecter."""
    s = JudgeScore(question_id="q1", judge="local")
    assert s.inject_recommended is False


def test_judge_score_invariant_answer():
    """INVARIANT : JudgeLocal ne produit jamais de contenu ameliore."""
    s = JudgeScore(question_id="q1", judge="local")
    assert s.improved_answer == ""


def test_judge_score_to_dict():
    s = JudgeScore(
        question_id="q1", judge="local",
        concept_score=0.8, coherence_score=0.7, structure_score=0.6,
        final_score=0.75, domain="python_core", palier=0,
        strengths=["clair"], weaknesses=["incomplet"],
    )
    d = s.to_dict()
    assert d["question_id"] == "q1"
    assert d["judge"] == "local"
    assert d["concept_score"] == 0.8
    assert d["final_score"] == 0.75
    assert d["inject_recommended"] is False
    assert d["improved_answer"] == ""
    assert d["strengths"] == ["clair"]
    assert d["weaknesses"] == ["incomplet"]


def test_judge_score_from_dict():
    s = JudgeScore(
        question_id="q2", judge="claude",
        concept_score=0.9, coherence_score=0.85, structure_score=0.8,
        final_score=0.85, inject_recommended=True,
        improved_answer="Meilleure reponse ici.",
        domain="python_core", palier=1,
    )
    reconstructed = JudgeScore.from_dict(s.to_dict())
    assert reconstructed.question_id == s.question_id
    assert reconstructed.judge == s.judge
    assert reconstructed.final_score == s.final_score
    assert reconstructed.inject_recommended is True
    assert reconstructed.improved_answer == "Meilleure reponse ici."


# ── ProbeResponse ─────────────────────────────────────────────────────────────

def test_probe_response_to_dict():
    q = BenchQuestion(
        id="q1", domain="python_core", palier=0,
        question="Qu'est-ce que le GIL ?",
        expected_concepts=["GIL"],
    )
    pr = ProbeResponse(
        question_id="q1", question=q,
        response="Le GIL est un verrou...",
        model="qwen2.5-coder:3b",
        duration_sec=1.23,
        timestamp="2026-04-24T00:00:00Z",
    )
    d = pr.to_dict()
    assert d["question_id"] == "q1"
    assert d["response"] == "Le GIL est un verrou..."
    assert d["model"] == "qwen2.5-coder:3b"
    assert d["duration_sec"] == 1.23
    assert isinstance(d["question"], dict)
    assert d["question"]["id"] == "q1"


def test_probe_response_from_dict():
    q = BenchQuestion(
        id="q1", domain="python_core", palier=0,
        question="Q ?", expected_concepts=["X"],
    )
    original = ProbeResponse(
        question_id="q1", question=q,
        response="Reponse test.",
        model="qwen2.5-coder:3b",
        duration_sec=2.5,
        timestamp="2026-04-24T12:00:00Z",
    )
    reconstructed = ProbeResponse.from_dict(original.to_dict())
    assert reconstructed.question_id == original.question_id
    assert reconstructed.response == original.response
    assert reconstructed.duration_sec == original.duration_sec
    assert reconstructed.question.id == "q1"


# ── DistilledSkill ────────────────────────────────────────────────────────────

def test_distilled_skill_score_threshold():
    """Un score de 0.70 est valide (egal au seuil min_inject_score)."""
    ds = DistilledSkill(
        question_id="q1", domain="python_core", palier=0,
        improved_answer="Explication GIL.",
        score=0.70,
        dedup_hash="abc123def456abcd",
        judge="claude",
    )
    assert ds.score >= _MIN_INJECT_SCORE


def test_distilled_skill_score_low():
    """Un score de 0.65 est inferieur au seuil (documenter le seuil)."""
    ds = DistilledSkill(
        question_id="q1", domain="python_core", palier=0,
        improved_answer="Explication insuffisante.",
        score=0.65,
        dedup_hash="000000000000abcd",
        judge="claude",
    )
    assert ds.score < _MIN_INJECT_SCORE


def test_distilled_skill_to_dict():
    ds = DistilledSkill(
        question_id="q3", domain="python_core", palier=1,
        improved_answer="Asyncio utilise une event loop...",
        score=0.85,
        dedup_hash="1234567890abcdef",
        judge="claude",
        injected_at="2026-04-24T01:00:00Z",
    )
    d = ds.to_dict()
    assert d["question_id"] == "q3"
    assert d["score"] == 0.85
    assert d["dedup_hash"] == "1234567890abcdef"
    assert d["judge"] == "claude"
    assert d["injected_at"] == "2026-04-24T01:00:00Z"
    reconstructed = DistilledSkill.from_dict(d)
    assert reconstructed.score == 0.85
    assert reconstructed.improved_answer == ds.improved_answer


# ── PalierState ───────────────────────────────────────────────────────────────

def test_palier_state_defaults():
    p = PalierState(domain="python_core")
    assert p.current_palier == 0
    assert p.avg_score == 0.0
    assert p.recent_scores == []
    assert p.sessions_completed == 0


def test_palier_state_to_dict():
    p = PalierState(
        domain="python_core",
        current_palier=1,
        questions_done=5,
        avg_score=0.78,
        unlock_threshold=0.70,
        sessions_completed=2,
        recent_scores=[0.72, 0.80, 0.78],
    )
    d = p.to_dict()
    assert d["domain"] == "python_core"
    assert d["current_palier"] == 1
    assert d["avg_score"] == 0.78
    assert d["recent_scores"] == [0.72, 0.80, 0.78]
    reconstructed = PalierState.from_dict(d)
    assert reconstructed.current_palier == 1
    assert reconstructed.recent_scores == [0.72, 0.80, 0.78]
