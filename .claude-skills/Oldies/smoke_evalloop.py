# -*- coding: utf-8-sig -*-
"""
smoke_evalloop.py — Test manuel EvalLoop V3 avec Ollama reel.

Lance depuis D:\LLMCodeAgent\ :
    python smoke_evalloop.py

Ce script ne modifie aucun fichier de session, ne met pas a jour eval_state.json.
C'est un smoke test interactif : probe 2 questions -> JudgeLocal -> affichage.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from EvalLoop.evalloop_types import BenchQuestion
from EvalLoop.engines.probe_engine import ProbeEngine
from EvalLoop.judges.judge_local import JudgeLocal

QUESTIONS = [
    BenchQuestion(
        id="python_core/p0/gil_001",
        domain="python_core",
        palier=0,
        question="Qu'est-ce que le GIL en Python et pourquoi existe-t-il ?",
        expected_concepts=["GIL", "Global Interpreter Lock", "thread", "memoire", "CPython"],
        rubric="Expliquer le role du GIL dans CPython et son impact sur le multi-threading.",
    ),
    BenchQuestion(
        id="python_core/p0/str_repr_001",
        domain="python_core",
        palier=0,
        question="Quelle est la difference entre __str__ et __repr__ en Python ?",
        expected_concepts=["__str__", "__repr__", "lisible", "debogage", "repr"],
        rubric="Distinguer usage utilisateur (__str__) et debogage (__repr__).",
    ),
]

SEP = "=" * 70


def run():
    engine = ProbeEngine()
    judge  = JudgeLocal()

    print(f"\n{SEP}")
    print("  SMOKE TEST EVALLOOP V3 — Ollama reel")
    print(f"  Modele : {engine._model}")
    print(SEP)

    for q in QUESTIONS:
        print(f"\n>>> Question : {q.id}")
        print(f"    {q.question}")
        print(f"    Concepts attendus : {q.expected_concepts}")
        print()

        print("    [ Probe en cours... ]")
        pr = engine.probe(q)
        print(f"    Duree : {pr.duration_sec}s")
        print()
        print("    --- Reponse brute ---")
        # Afficher les 400 premiers chars pour ne pas saturer le terminal
        excerpt = pr.response[:400]
        if len(pr.response) > 400:
            excerpt += f"\n    ... [{len(pr.response)} chars total]"
        print(excerpt)
        print()

        score = judge.score(q, pr)
        found   = judge._find_concepts(pr.response, q.expected_concepts)
        missing = [c for c in q.expected_concepts if c not in found]

        print("    --- Scores JudgeLocal ---")
        print(f"    concept_score   : {score.concept_score:.3f}")
        print(f"    coherence_score : {score.coherence_score:.3f}")
        print(f"    structure_score : {score.structure_score:.3f}")
        print(f"    final_score     : {score.final_score:.3f}")
        print(f"    Concepts trouves  : {sorted(found)}")
        print(f"    Concepts manquants: {missing}")
        gk = "PASSE" if score.final_score >= 0.30 else "BLOQUE (sous gatekeeper_min=0.30)"
        print(f"    Gatekeeper        : {gk}")
        print()

    print(SEP)
    print("  Smoke test termine.")
    print(SEP)


if __name__ == "__main__":
    run()
