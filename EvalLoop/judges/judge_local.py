# -*- coding: utf-8-sig -*-
"""
judge_local.py — EVAL-02
Juge offline : gatekeeper avant JudgeClaude.

Scoring base sur :
  - concept_score  (60%) : matching accent-insensible + support operateurs speciaux
  - coherence_score(20%) : concepts regroupes dans fenetre de 100 mots (anti-stuffing)
  - structure_score(20%) : code blocks / listes / exemples (max 0.30)

INVARIANTS ABSOLUS :
  inject_recommended = False  (JudgeLocal ne decide jamais d'injecter)
  improved_answer    = ""     (JudgeLocal ne produit jamais de contenu ameliore)

FIX-JUDGE-01 (2026-04-24) :
  - Normalisation NFD : 'memoire' matche 'memoire' dans le texte
  - Support operateurs : '==' et '__str__' utilisent lookahead/lookbehind
    car \\b ne fonctionne pas sur les caracteres non-alphanum

FIX-JUDGE-02 (2026-04-24) :
  - _structure_score() : listes numerotees (1. 2. 3.) desormais detectees
    en plus des tirets/asterisques -- regex '^\\s*([-*]|\\d+\\.)\\s'
"""
from __future__ import annotations

import re
import unicodedata
from typing import List

from EvalLoop.evalloop_types import BenchQuestion, JudgeScore, ProbeResponse
from EvalLoop.judges.judge_base import JudgeBase


class JudgeLocal(JudgeBase):
    """
    Gatekeeper offline -- evalue la surface des reponses.

    Son seul role est de filtrer les reponses catastrophiques avant JudgeClaude.
    Ne produit jamais de contenu ameliore et ne decide jamais d'injecter.
    """

    def score(self, question: BenchQuestion, response: ProbeResponse) -> JudgeScore:
        text = response.response

        concept_score   = self._concept_score(text, question.expected_concepts)
        coherence_score = self._coherence_score(text, question.expected_concepts)
        structure_score = self._structure_score(text)
        final_score     = (
            concept_score   * 0.6
            + coherence_score * 0.2
            + structure_score * 0.2
        )

        found   = self._find_concepts(text, question.expected_concepts)
        missing = [c for c in question.expected_concepts if c not in found]

        return JudgeScore(
            question_id        = question.id,
            judge              = "local",
            concept_score      = round(concept_score, 3),
            coherence_score    = round(coherence_score, 3),
            structure_score    = round(structure_score, 3),
            final_score        = round(final_score, 3),
            inject_recommended = False,  # INVARIANT
            improved_answer    = "",     # INVARIANT
            domain             = question.domain,
            palier             = question.palier,
            weaknesses         = [f"Concept manquant : {c}" for c in missing],
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(s: str) -> str:
        """
        Normalise NFD puis encode ASCII (ignore) pour matching accent-insensible.
        'memoire' matche 'memoire', 'egalite' matche 'egalite', etc.
        Retourne la chaine en minuscules sans accents.
        """
        return (
            unicodedata.normalize('NFD', s)
            .encode('ascii', 'ignore')
            .decode('ascii')
            .lower()
        )

    def _find_concepts(self, text: str, concepts: List[str]) -> set:
        """
        Matching insensible aux accents ET aux bornes de mots.

        Deux strategies selon le type de concept :
          - Concept purement alphanum (ex: 'GIL', 'thread', 'memoire') :
              \\bword\\b classique sur le texte normalise NFD.
          - Concept avec caracteres speciaux (ex: '==', '__str__', '*args') :
              lookahead/lookbehind [^a-z0-9_] car \\b ne fonctionne pas
              sur les operateurs et caracteres non-alphanum.
        """
        text_norm = self._normalize(text)
        found = set()
        for c in concepts:
            c_norm = self._normalize(c)
            if not c_norm:
                continue
            if re.match(r'^[a-z0-9]+$', c_norm):
                # Concept purement alphanum : \b suffit
                pattern = r'\b' + re.escape(c_norm) + r'\b'
            else:
                # Concept avec caracteres speciaux : lookahead/lookbehind
                pattern = r'(?<![a-z0-9])' + re.escape(c_norm) + r'(?![a-z0-9])'
            if re.search(pattern, text_norm):
                found.add(c)
        return found

    def _concept_score(self, text: str, concepts: List[str]) -> float:
        """Ratio de concepts trouves parmi les expected_concepts."""
        if not concepts:
            return 1.0
        found = self._find_concepts(text, concepts)
        return len(found) / len(concepts)

    def _coherence_score(self, text: str, concepts: List[str]) -> float:
        """
        Verifie que les concepts trouves sont regroupes dans une fenetre de 100 mots.
        Penalise le keyword stuffing (concepts eparpilles dans une longue reponse).
        """
        if not concepts:
            return 1.0
        words = text.lower().split()
        if len(words) < 3:
            return 0.0

        window = 100
        best   = 0.0
        for i in range(len(words)):
            chunk = " ".join(words[i:i + window])
            found_in_window = self._find_concepts(chunk, concepts)
            ratio = len(found_in_window) / len(concepts)
            if ratio > best:
                best = ratio
        return best

    def _structure_score(self, text: str) -> float:
        """
        Evalue la qualite structurelle (remplace le simple length_score).
        Code blocks  -> +0.1
        Listes       -> +0.1
        Exemples     -> +0.1
        Maximum : 0.3 (poids 20% du final_score -> contribue max 0.06)
        """
        s = 0.0
        if "```" in text:
            s += 0.1
        if re.search(r'^\s*([-*]|\d+\.)\s', text, re.MULTILINE):
            s += 0.1
        if re.search(
            r'\b(exemple|ex\s*:|ex:|>>>|par exemple)\b',
            text,
            re.IGNORECASE,
        ):
            s += 0.1
        return min(s, 0.3)
