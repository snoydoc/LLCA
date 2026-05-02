# -*- coding: utf-8-sig -*-
"""
error_analyzer.py — LCCA V5 Fusion
Sprint 06 — TASK-06-04
REFACTO-13 — Orchestration légère (~5 KB).
  - Classifieurs extraits dans error_classifier.py
  - Logique recovery extraite dans error_recovery_hints.py
  - Aliases rétrocompat maintenus : analyze_syntax_error, analyze_import_error,
    analyze_generic, generate_fix_prompt, try_auto_fix

Usage :
    from core.error_analyzer import ErrorAnalyzer, ErrorReport
    analyzer = ErrorAnalyzer()
    report = analyzer.analyze(e, "auth.py", source_code)
    prompt  = analyzer.generate_fix_prompt(report, context)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger("lcca.error_analyzer")


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class ErrorReport:
    """Rapport d'erreur structuré et actionnable."""
    error_type:   str
    file:         str
    line:         Optional[int]
    message:      str
    suggestion:   str
    severity:     str        # "blocking" | "warning" | "info"
    auto_fixable: bool


# ── ErrorAnalyzer (orchestration légère) ─────────────────────────────────────

class ErrorAnalyzer:
    r"""
    Analyse les exceptions Python et produit des ErrorReport actionnables.

    Délègue la classification à ErrorClassifier et la récupération
    à ErrorRecoveryHints.

    Méthodes publiques (rétrocompat complète) :
        analyze()              — Dispatch vers le bon classifieur
        analyze_syntax_error() — Alias rétrocompat → ErrorClassifier.classify_syntax
        analyze_import_error() — Alias rétrocompat → ErrorClassifier.classify_import
        analyze_generic()      — Alias rétrocompat → ErrorClassifier.classify_generic
        generate_fix_prompt()  — Alias rétrocompat → ErrorRecoveryHints.build_fix_prompt
        try_auto_fix()         — Alias rétrocompat → ErrorRecoveryHints.try_auto_fix
    """

    def __init__(self, requirements_path: Optional[Path] = None) -> None:
        from core.error_recovery_hints import ErrorRecoveryHints
        self._hints = ErrorRecoveryHints(requirements_path=requirements_path)

    # ── Interface principale ──────────────────────────────────────────────────

    def analyze(
        self,
        error: Exception,
        file_path: str,
        source: str = "",
    ) -> ErrorReport:
        """
        Dispatch vers le classifieur spécialisé selon le type d'exception.

        Args:
            error:     Exception levée (SyntaxError, ImportError, etc.)
            file_path: Chemin du fichier concerné.
            source:    Contenu source du fichier (non utilisé, rétrocompat).

        Returns:
            ErrorReport avec suggestion non vide.
        """
        from core.error_classifier import ErrorClassifier
        return ErrorClassifier.classify(
            error,
            file_path,
            auto_fixable_fn=self._hints.is_module_fixable,
        )

    # ── Aliases rétrocompat ───────────────────────────────────────────────────

    def analyze_syntax_error(self, e: SyntaxError, file_path: str) -> ErrorReport:
        """Rétrocompat — délègue à ErrorClassifier.classify_syntax."""
        from core.error_classifier import ErrorClassifier
        return ErrorClassifier.classify_syntax(e, file_path)

    def analyze_import_error(self, e: ImportError, file_path: str) -> ErrorReport:
        """Rétrocompat — délègue à ErrorClassifier.classify_import."""
        from core.error_classifier import ErrorClassifier
        module = ErrorClassifier._extract_module_name(str(e))
        auto_fixable = self._hints.is_module_fixable(module) if module else False
        return ErrorClassifier.classify_import(e, file_path, auto_fixable)

    def analyze_generic(self, e: Exception, file_path: str) -> ErrorReport:
        """Rétrocompat — délègue à ErrorClassifier.classify_generic."""
        from core.error_classifier import ErrorClassifier
        return ErrorClassifier.classify_generic(e, file_path)

    def generate_fix_prompt(self, report: ErrorReport, context: str = "") -> str:
        """Rétrocompat — délègue à ErrorRecoveryHints.build_fix_prompt."""
        return self._hints.build_fix_prompt(report, context)

    def try_auto_fix(
        self, report: ErrorReport, patcher, workspace: Optional[Path] = None
    ) -> bool:
        """Rétrocompat — délègue à ErrorRecoveryHints.try_auto_fix."""
        return self._hints.try_auto_fix(report, patcher, workspace)

    # ── Helpers exposés pour rétrocompat tests ────────────────────────────────

    @staticmethod
    def _extract_module_name(error_msg: str) -> Optional[str]:
        """Rétrocompat — délègue à ErrorClassifier._extract_module_name."""
        from core.error_classifier import ErrorClassifier
        return ErrorClassifier._extract_module_name(error_msg)

    def _is_in_requirements(self, module: str) -> bool:
        """Rétrocompat — délègue à ErrorRecoveryHints.is_module_fixable."""
        return self._hints.is_module_fixable(module)

    @staticmethod
    def _get_line_context(text: str, line_idx: int, n: int = 2) -> str:
        """Rétrocompat — délègue à ErrorClassifier._get_line_context."""
        from core.error_classifier import ErrorClassifier
        return ErrorClassifier._get_line_context(text, line_idx, n)
