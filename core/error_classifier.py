# -*- coding: utf-8-sig -*-
"""
error_classifier.py — LCCA V5 Fusion
REFACTO-13 — Extrait de error_analyzer.py

Classifieurs d'erreurs Python par type : SyntaxError, ImportError,
AttributeError, NameError et fallback générique.

Chaque méthode prend l'exception + le chemin fichier et retourne
un ErrorReport. Aucune dépendance sur requirements.txt ici (voir
error_recovery_hints.py pour la logique auto_fixable).

Usage interne :
    from core.error_classifier import ErrorClassifier
    report = ErrorClassifier.classify_syntax(e, "auth.py")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# Import local de la dataclass (pas de dépendance circulaire — error_report.py
# ou error_analyzer.py peuvent exposer ErrorReport en re-export).
from core.error_analyzer import ErrorReport

_SYNTAX_SUGGESTIONS: dict[str, str] = {
    "unexpected indent":    "Indentation incorrecte ligne {line}. Vérifier les espaces/tabs.",
    "expected an indented": "Bloc attendu mais non indenté ligne {line}.",
    "unindent does not":    "Désindentation incohérente ligne {line}. Vérifier les niveaux.",
    "unexpected EOF":       "Fin de fichier inattendue. Parenthèse, accolade ou guillemet non fermé.",
    "invalid syntax":       "Syntaxe invalide ligne {line}. Contexte: {context}",
    "EOL while scanning":   "Chaîne non fermée ligne {line}. Vérifier les guillemets.",
}


class ErrorClassifier:
    """
    Classifie les exceptions Python en ErrorReport structurés.

    Toutes les méthodes sont statiques — pas d'état interne.
    La logique auto_fixable (requirements.txt) est déléguée
    à ErrorRecoveryHints via error_analyzer.py.

    Méthodes :
        classify(error, file_path, auto_fixable_fn) — dispatch principal
        classify_syntax(e, file_path)               — SyntaxError
        classify_import(e, file_path, auto_fixable) — ImportError
        classify_attribute(e, file_path)            — AttributeError
        classify_name(e, file_path)                 — NameError
        classify_generic(e, file_path)              — fallback
    """

    @staticmethod
    def classify(
        error: Exception,
        file_path: str,
        auto_fixable_fn=None,
    ) -> ErrorReport:
        """
        Dispatch vers le classifieur spécialisé selon le type d'exception.

        Args:
            error:           Exception Python à analyser.
            file_path:       Chemin du fichier source.
            auto_fixable_fn: callable(module_name) → bool, fourni par ErrorAnalyzer
                             pour la logique requirements.txt.

        Returns:
            ErrorReport structuré avec suggestion non vide.
        """
        if isinstance(error, SyntaxError):
            return ErrorClassifier.classify_syntax(error, file_path)

        if isinstance(error, (ImportError, ModuleNotFoundError)):
            module = ErrorClassifier._extract_module_name(str(error))
            auto_fixable = bool(auto_fixable_fn and module and auto_fixable_fn(module))
            return ErrorClassifier.classify_import(error, file_path, auto_fixable)

        if isinstance(error, AttributeError):
            return ErrorClassifier.classify_attribute(error, file_path)

        if isinstance(error, NameError):
            return ErrorClassifier.classify_name(error, file_path)

        return ErrorClassifier.classify_generic(error, file_path)

    # ── SyntaxError ───────────────────────────────────────────────────────────

    @staticmethod
    def classify_syntax(e: SyntaxError, file_path: str) -> ErrorReport:
        """
        Analyse une SyntaxError et produit une suggestion contextualisée.

        Couvre : IndentationError, unexpected EOF, invalid syntax, EOL, etc.
        """
        msg_lower = (e.msg or "").lower()
        line = e.lineno
        context = ErrorClassifier._get_line_context(e.text or "", 0, n=1)

        suggestion = ""
        for pattern, tmpl in _SYNTAX_SUGGESTIONS.items():
            if pattern in msg_lower:
                suggestion = tmpl.format(line=line, context=context)
                break

        if not suggestion:
            suggestion = f"SyntaxError ligne {line}: {e.msg}. Contexte: {context}"

        return ErrorReport(
            error_type="SyntaxError",
            file=file_path,
            line=line,
            message=str(e),
            suggestion=suggestion,
            severity="blocking",
            auto_fixable=False,
        )

    # ── ImportError ───────────────────────────────────────────────────────────

    @staticmethod
    def classify_import(
        e: ImportError,
        file_path: str,
        auto_fixable: bool = False,
    ) -> ErrorReport:
        """
        Analyse une ImportError.

        auto_fixable est fourni par l'appelant (ErrorAnalyzer via _is_in_requirements).
        """
        module_name = ErrorClassifier._extract_module_name(str(e))

        if module_name:
            suggestion = (
                f"Module '{module_name}' manquant. "
                f"Ajouter 'import {module_name}' ou installer via pip."
            )
        else:
            suggestion = f"ImportError: {e}. Vérifier les imports du fichier."

        return ErrorReport(
            error_type="ImportError",
            file=file_path,
            line=None,
            message=str(e),
            suggestion=suggestion,
            severity="blocking",
            auto_fixable=auto_fixable,
        )

    # ── AttributeError ────────────────────────────────────────────────────────

    @staticmethod
    def classify_attribute(e: AttributeError, file_path: str) -> ErrorReport:
        """Analyse AttributeError: 'X' object has no attribute 'Y'."""
        match = re.search(
            r"'([^']+)' object has no attribute '([^']+)'", str(e)
        )
        if match:
            obj_type, attr = match.group(1), match.group(2)
            suggestion = (
                f"L'objet '{obj_type}' n'a pas d'attribut '{attr}'. "
                "Vérifier le type retourné ou l'orthographe de l'attribut."
            )
        else:
            suggestion = f"AttributeError: {e}. Vérifier les accès d'attributs."

        return ErrorReport(
            error_type="AttributeError",
            file=file_path,
            line=None,
            message=str(e),
            suggestion=suggestion,
            severity="blocking",
            auto_fixable=False,
        )

    # ── NameError ─────────────────────────────────────────────────────────────

    @staticmethod
    def classify_name(e: NameError, file_path: str) -> ErrorReport:
        """Analyse NameError: name 'X' is not defined."""
        match = re.search(r"name '([^']+)' is not defined", str(e))
        name = match.group(1) if match else "inconnue"
        suggestion = (
            f"Variable '{name}' utilisée avant définition. "
            "Vérifier la portée (scope) ou ajouter une définition en amont."
        )
        return ErrorReport(
            error_type="NameError",
            file=file_path,
            line=None,
            message=str(e),
            suggestion=suggestion,
            severity="blocking",
            auto_fixable=False,
        )

    # ── Fallback générique ────────────────────────────────────────────────────

    @staticmethod
    def classify_generic(e: Exception, file_path: str) -> ErrorReport:
        """Rapport générique pour les exceptions non spécialisées."""
        return ErrorReport(
            error_type=type(e).__name__,
            file=file_path,
            line=None,
            message=str(e),
            suggestion=f"{type(e).__name__} dans {file_path}: {e}",
            severity="warning",
            auto_fixable=False,
        )

    # ── Helpers statiques ────────────────────────────────────────────────────

    @staticmethod
    def _extract_module_name(error_msg: str) -> Optional[str]:
        """
        Extrait le nom du module depuis un message ImportError.
        Ex: "No module named 'requests'" → "requests"
            "cannot import name 'foo' from 'bar'" → "bar"
        """
        m = re.search(r"No module named '([^']+)'", error_msg)
        if m:
            return m.group(1).split(".")[0]
        m = re.search(r"from '([^']+)'", error_msg)
        if m:
            return m.group(1).split(".")[0]
        return None

    @staticmethod
    def _get_line_context(text: str, line_idx: int, n: int = 2) -> str:
        """Retourne n lignes autour de line_idx depuis un texte multi-lignes."""
        if not text:
            return ""
        lines = text.splitlines()
        start = max(0, line_idx - n)
        end   = min(len(lines), line_idx + n + 1)
        return " | ".join(lines[start:end]).strip()
