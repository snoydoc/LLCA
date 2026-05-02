# -*- coding: utf-8-sig -*-
"""
test_eval_02_judge.py -- Tests EVAL-02 : ProbeEngine + JudgeLocal
15 tests couvrant l'instanciation, les invariants, le scoring et le gatekeeper.
OllamaClient est toujours mocke -- aucun appel reseau reel.
"""
import pytest
from unittest.mock import MagicMock, patch

from EvalLoop.evalloop_types import BenchQuestion, ProbeResponse, JudgeScore
from EvalLoop.engines.probe_engine import ProbeEngine
from EvalLoop.judges.judge_base import JudgeBase
from EvalLoop.judges.judge_local import JudgeLocal


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_question(
    concepts=None,
    question_text="Qu'est-ce que le GIL ?",
    qid="q_test",
    domain="python_core",
    palier=0,
):
    return BenchQuestion(
        id=qid,
        domain=domain,
        palier=palier,
        question=question_text,
        expected_concepts=concepts if concepts is not None else ["GIL", "thread"],
    )


def _make_probe_response(question, response_text):
    return ProbeResponse(
        question_id=question.id,
        question=question,
        response=response_text,
        model="qwen2.5-coder:3b",
        duration_sec=1.0,
        timestamp="2026-04-24T00:00:00Z",
    )


# ── ProbeEngine ───────────────────────────────────────────────────────────────

def test_probe_engine_instanciation():
    """Instancie sans erreur avec OllamaClient mocke."""
    with patch("EvalLoop.engines.probe_engine.OllamaClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        engine = ProbeEngine(model="test-model", base_url="http://localhost:11434")
        assert engine is not None
        mock_cls.assert_called_once()


def test_probe_returns_probe_response():
    """probe() retourne un ProbeResponse correctement forme."""
    with patch("EvalLoop.engines.probe_engine.OllamaClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.generate.return_value = "Le GIL est un verrou global."
        mock_cls.return_value = mock_client

        engine = ProbeEngine(model="qwen2.5-coder:3b")
        q = _make_question()
        pr = engine.probe(q)

        assert isinstance(pr, ProbeResponse)
        assert pr.question_id == "q_test"
        assert pr.response == "Le GIL est un verrou global."
        assert pr.model == "qwen2.5-coder:3b"
        assert pr.duration_sec >= 0.0
        assert "T" in pr.timestamp  # ISO 8601


def test_probe_timeout_is_none():
    """OllamaClient doit recevoir timeout=None (invariant LCCA)."""
    with patch("EvalLoop.engines.probe_engine.OllamaClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        ProbeEngine()
        _, kwargs = mock_cls.call_args
        assert kwargs.get("timeout") is None


# ── JudgeLocal -- Invariants ──────────────────────────────────────────────────

def test_judge_local_never_injects():
    """INVARIANT : inject_recommended est toujours False."""
    judge = JudgeLocal()
    q  = _make_question(["GIL"])
    pr = _make_probe_response(q, "Le GIL protege l'interpreteur Python.")
    s  = judge.score(q, pr)
    assert s.inject_recommended is False


def test_judge_local_no_improved_answer():
    """INVARIANT : improved_answer est toujours une chaine vide."""
    judge = JudgeLocal()
    q  = _make_question(["GIL"])
    pr = _make_probe_response(q, "Le GIL est un verrou.")
    s  = judge.score(q, pr)
    assert s.improved_answer == ""


# ── JudgeLocal -- Concept score ───────────────────────────────────────────────

def test_judge_local_full_concepts():
    """Tous les concepts presents -> concept_score == 1.0."""
    judge = JudgeLocal()
    q  = _make_question(["GIL", "thread"])
    pr = _make_probe_response(q, "Le GIL empeche l'execution parallele des thread Python.")
    s  = judge.score(q, pr)
    assert s.concept_score == 1.0


def test_judge_local_no_concepts():
    """Aucun concept trouve -> concept_score == 0.0."""
    judge = JudgeLocal()
    q  = _make_question(["GIL", "thread"])
    pr = _make_probe_response(q, "Python est un langage de programmation.")
    s  = judge.score(q, pr)
    assert s.concept_score == 0.0


def test_judge_local_tokenization():
    """'list' ne doit pas matcher 'listing' ni 'blacklist'."""
    judge = JudgeLocal()
    q  = _make_question(["list"])
    # "listing" et "blacklist" contiennent "list" mais ne sont pas le token exact
    pr = _make_probe_response(q, "Voici un listing complet de la blacklist.")
    s  = judge.score(q, pr)
    assert s.concept_score == 0.0


def test_judge_local_case_insensitive():
    """'GIL' doit matcher 'gil' dans la reponse (insensible a la casse)."""
    judge = JudgeLocal()
    q  = _make_question(["GIL"])
    pr = _make_probe_response(q, "Le gil est un mecanisme de verrou.")
    s  = judge.score(q, pr)
    assert s.concept_score == 1.0


# ── JudgeLocal -- Coherence score ─────────────────────────────────────────────

def test_judge_local_keyword_stuffing():
    """Concepts eparpilles dans un long texte -> coherence_score bas -> final_score < 0.5."""
    judge = JudgeLocal()
    q = _make_question(["GIL", "thread", "asyncio", "coroutine"])
    # Chaque concept est separe par ~150 mots de remplissage
    filler = " ".join(["mot"] * 150)
    text = f"GIL {filler} thread {filler} asyncio {filler} coroutine"
    pr = _make_probe_response(q, text)
    s  = judge.score(q, pr)
    # Tous les concepts sont la (concept_score=1.0) mais eparpilles
    assert s.concept_score == 1.0
    assert s.coherence_score < 0.5
    assert s.final_score < 0.8  # coherence penalise le score final


def test_judge_local_grouped_concepts():
    """Concepts regroupes dans une fenetre courte -> coherence_score eleve."""
    judge = JudgeLocal()
    q  = _make_question(["GIL", "thread"])
    pr = _make_probe_response(
        q,
        "Le GIL (Global Interpreter Lock) est un verrou qui empeche plusieurs thread "
        "d'executer du bytecode Python simultanement.",
    )
    s = judge.score(q, pr)
    assert s.coherence_score >= 0.8


# ── JudgeLocal -- Structure score ─────────────────────────────────────────────

def test_judge_local_code_block():
    """Presence de '```' -> structure_score >= 0.1."""
    judge = JudgeLocal()
    q  = _make_question([])
    pr = _make_probe_response(q, "Exemple :\n```python\nimport threading\n```")
    s  = judge.score(q, pr)
    assert s.structure_score >= 0.1


def test_judge_local_list_bonus():
    """Presence d'une liste markdown '- item' -> structure_score >= 0.1."""
    judge = JudgeLocal()
    q  = _make_question([])
    pr = _make_probe_response(q, "Points cles :\n- verrou global\n- thread unique")
    s  = judge.score(q, pr)
    assert s.structure_score >= 0.1


def test_judge_local_no_structure():
    """Texte plat sans code ni liste ni exemple -> structure_score == 0.0."""
    judge = JudgeLocal()
    q  = _make_question([])
    pr = _make_probe_response(q, "Python est un langage interprete tres populaire.")
    s  = judge.score(q, pr)
    assert s.structure_score == 0.0


# ── JudgeLocal -- Gatekeeper ──────────────────────────────────────────────────

def test_judge_local_gatekeeper_threshold():
    """Reponse vide -> final_score < 0.30 (en dessous du seuil gatekeeper_min)."""
    judge = JudgeLocal()
    q  = _make_question(["GIL", "thread", "lock", "bytecode"])
    pr = _make_probe_response(q, "")
    s  = judge.score(q, pr)
    assert s.final_score < 0.30


# ── FIX-JUDGE-01 : accents + operateurs ──────────────────────────────────────

def test_judge_local_accent_normalization():
    """'memoire' (concept sans accent) doit matcher 'memoire' dans le texte (accentue)."""
    judge = JudgeLocal()
    q  = _make_question(["memoire", "GIL"])
    pr = _make_probe_response(q, "Le GIL protege la memoire de l'interpreteur CPython.")
    s  = judge.score(q, pr)
    assert s.concept_score == 1.0, f"Expected 1.0, got {s.concept_score} — accents non normalises"


def test_judge_local_operator_concept():
    """'==' (operateur) doit matcher dans un texte contenant '=='."""
    judge = JudgeLocal()
    q  = _make_question(["==", "is", "identite"])
    pr = _make_probe_response(
        q,
        "En Python, == compare les valeurs tandis que is verifie l'identite des objets."
    )
    s  = judge.score(q, pr)
    assert s.concept_score == 1.0, f"Expected 1.0, got {s.concept_score} — operateurs non detectes"


def test_judge_local_dunder_concept():
    """'__str__' (dunder) doit matcher dans un texte contenant '__str__'."""
    judge = JudgeLocal()
    q  = _make_question(["__str__", "__repr__"])
    pr = _make_probe_response(
        q,
        "La methode __str__ est pour l'affichage, __repr__ pour le debogage."
    )
    s  = judge.score(q, pr)
    assert s.concept_score == 1.0, f"Expected 1.0, got {s.concept_score} — dunders non detectes"
