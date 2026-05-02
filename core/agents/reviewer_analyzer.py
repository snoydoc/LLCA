# -*- coding: utf-8-sig -*-
"""
LCCA REFACTO-09 -- ReviewerLlmAnalyzer : analyse qualitative LLM du code (V9-08).

Responsabilite unique :
    Appeler le LLM pour obtenir un score de qualite, une liste de problemes
    et des suggestions d'amelioration sur un snippet de code Python.

Classe :
    ReviewerLlmAnalyzer(llm_generator)
        .analyze(code, intent, domain) -> dict

Le dict retourne toujours les 3 cles : quality_score (int), issues (list), suggestions (list).
Valeurs neutres si LLM absent ou erreur : quality_score=-1, issues=[], suggestions=[].

Prompts (module-level, accessibles pour les tests) :
    REVIEWER_SYSTEM   -- prompt systeme
    REVIEWER_USER_TMPL -- template prompt utilisateur
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts LLM
# ---------------------------------------------------------------------------

REVIEWER_SYSTEM = (
    "You are a senior Python code reviewer. "
    "Analyze the code provided and return a short JSON object with keys: "
    '"quality_score" (int 0-100), "issues" (list of strings), "suggestions" (list of strings). '
    "Return ONLY valid JSON, no explanation."
)

REVIEWER_USER_TMPL = (
    "Domain: {domain}\n"
    "Task: {intent}\n"
    "Code to review:\n```python\n{code}\n```\n\n"
    "Return JSON only."
)

# Aliases prives pour retrocompat eventuelle
_REVIEWER_SYSTEM = REVIEWER_SYSTEM
_REVIEWER_USER_TMPL = REVIEWER_USER_TMPL

# Valeurs neutres retournees quand l'analyse est impossible
_NEUTRAL_RESULT: dict = {"quality_score": -1, "issues": [], "suggestions": []}


# ---------------------------------------------------------------------------
# ReviewerLlmAnalyzer
# ---------------------------------------------------------------------------

class ReviewerLlmAnalyzer:
    """
    Couche d'analyse LLM isolee du ReviewerAgent.

    Parametres
    ----------
    llm_generator : LLMGenerator ou None
        Si None, toutes les analyses retournent les valeurs neutres.
    """

    def __init__(self, llm_generator=None) -> None:
        self._llm = llm_generator

    def analyze(self, code: str, intent: str, domain: str) -> dict:
        """
        Analyse qualitative du code via LLM.

        Returns
        -------
        dict
            quality_score (int), issues (list[str]), suggestions (list[str]).
            Retourne valeurs neutres si LLM absent ou erreur (jamais d'exception).
        """
        if self._llm is None:
            return dict(_NEUTRAL_RESULT)
        try:
            import json as _json
            user_prompt = REVIEWER_USER_TMPL.format(
                domain=domain,
                intent=intent,
                code=code[:1500],  # limite contexte
            )
            raw = self._llm.generate_text(REVIEWER_SYSTEM, user_prompt)
            # Nettoyer les fences markdown eventuelles
            clean = raw.strip()
            if clean.startswith("```"):
                lines = clean.splitlines()
                clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            parsed = _json.loads(clean)
            return {
                "quality_score": int(parsed.get("quality_score", -1)),
                "issues"       : list(parsed.get("issues", [])),
                "suggestions"  : list(parsed.get("suggestions", [])),
            }
        except Exception as exc:
            logger.debug("[reviewer_analyzer] LLM analysis failed: %s", exc)
            return dict(_NEUTRAL_RESULT)
