# -*- coding: utf-8-sig -*-
"""
LCCA REFACTO-09 -- ReviewerValidator : validation statique du code Python.

Responsabilite unique :
    Verifier la compilabilite Python d'un snippet de code et construire
    une reflexion lisible pour l'ArchitectAgent en cas d'echec.

Fonctions module-level (reimportees dans reviewer_agent pour retrocompat) :
    _check_syntax(code)      -> (bool, List[str])
    _build_reflection(...)   -> str
"""
from __future__ import annotations

from typing import List, Tuple


# ---------------------------------------------------------------------------
# Validation syntaxique
# ---------------------------------------------------------------------------

def _check_syntax(code: str) -> Tuple[bool, List[str]]:
    """
    Verifie la compilabilite Python du code.

    Retourne (ok, [issues]).
    Silencieux sur code vide : retourne (False, ["Code vide"]).
    """
    if not code or not code.strip():
        return False, ["Code vide"]
    try:
        compile(code, "<review>", "exec")
        return True, []
    except SyntaxError as exc:
        line_info = f" ligne {exc.lineno}" if exc.lineno else ""
        return False, [f"SyntaxError{line_info}: {exc.msg}"]
    except Exception as exc:
        return False, [str(exc)]


# ---------------------------------------------------------------------------
# Construction de la reflexion
# ---------------------------------------------------------------------------

def _build_reflection(issues: List[str], error_suggestion: str = "") -> str:
    """
    Formate une reflexion lisible pour l'ArchitectAgent.

    Format :
        "Reviewer: <issues>. Suggestion: <error_suggestion>"
    """
    issues_str = "; ".join(issues) if issues else "probleme inconnu"
    if error_suggestion:
        return f"Reviewer: {issues_str}. Suggestion: {error_suggestion}"
    return f"Reviewer: {issues_str}"
