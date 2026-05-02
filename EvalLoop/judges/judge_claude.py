# -*- coding: utf-8-sig -*-
"""
judge_claude.py — Juge qualitatif via API Anthropic (stub V3).

En V3, ce juge retourne des scores et une improved_answer hardcodés pour
permettre les tests de DistillEngine sans appel réseau réel.

En V4 : remplacer le corps de score() par un appel API Anthropic.

INVARIANTS (à l'inverse de JudgeLocal) :
  - inject_recommended = True  (si score >= seuil)
  - improved_answer != ""      (contenu généré ou hardcodé)
  - judge = "claude"           (toujours)

Conditions d'activation dans le pipeline :
  - Flag --judge claude au CLI lcca_eval.py
  - JudgeLocal.final_score >= gatekeeper_min (0.30)
"""
from __future__ import annotations

from EvalLoop.judges.judge_base import JudgeBase
from EvalLoop.evalloop_types import BenchQuestion, JudgeScore, ProbeResponse


class JudgeClaude(JudgeBase):
    """
    Juge qualitatif via API Anthropic.

    Seul juge autorisé à produire inject_recommended=True et improved_answer non vide.
    """

    def __init__(self, api_key: str = None):
        # En V3 : stub. Remplacer par appel API Anthropic en V4.
        self._api_key = api_key

    def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
        """
        Stub V3 : retourne un score fixe avec improved_answer hardcodé pour les tests.
        Remplacer le corps par un appel API Anthropic en production (V4).

        TODO V4 : construire le prompt depuis question.rubric + response.response,
        appeler l'API Anthropic, parser la réponse structurée → improved_answer + scores.
        """
        return JudgeScore(
            question_id        = question.id,
            judge              = "claude",
            concept_score      = 0.8,
            coherence_score    = 0.7,
            structure_score    = 0.3,
            final_score        = 0.74,
            inject_recommended = True,
            improved_answer    = f"[STUB] Réponse améliorée pour : {question.question[:50]}",
            domain             = question.domain,
            palier             = question.palier,
        )
