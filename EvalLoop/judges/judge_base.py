# -*- coding: utf-8-sig -*-
"""
judge_base.py — EVAL-02
ABC JudgeBase : contrat minimal pour tout juge EvalLoop.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from EvalLoop.evalloop_types import BenchQuestion, JudgeScore, ProbeResponse


class JudgeBase(ABC):
    """Interface commune a tous les juges EvalLoop (local, claude, ...)."""

    @abstractmethod
    def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
        """
        Evalue une reponse et retourne un JudgeScore.
        Les juges ne doivent jamais faire d'effets de bord (pas d'ecriture disque).
        """
        ...
