# -*- coding: utf-8-sig -*-
"""
code_evaluator.py — LCCA V5 Fusion
Sprint 11 — Feature: Évaluation qualité du code généré
Sprint REFACTO-01 — CriterionScore + _CriteriaScorer extraits dans
                    code_evaluator_criteria.py. Rétrocompat : les deux
                    classes restent importables depuis ce module (noqa: F401).

Évalue la qualité d'un code Python généré par le LLM sur une échelle 0-100.
L'évaluation est purement statique (AST + heuristiques), sans exécution.

Architecture :
    CodeEvaluator     — Interface publique : code str → EvaluationResult
    EvaluationResult  — Dataclass résultat avec score + détails par critère
    CriterionScore    — Ré-exporté depuis code_evaluator_criteria
    _CriteriaScorer   — Ré-exporté depuis code_evaluator_criteria

Critères évalués (total = 100 pts) :
    1. Syntaxe Python valide          — 30 pts (bloquant : 0 si invalide)
    2. Présence de type hints         — 20 pts (args + return)
    3. Présence de docstring          — 20 pts (module + fonctions/classes)
    4. Complexité cyclomatique        — 15 pts (plus simple = meilleur)
    5. Absence d'anti-patterns        — 15 pts (bare except, print, globals...)

Usage :
    from core.code_evaluator import CodeEvaluator

    ev = CodeEvaluator()
    result = ev.evaluate(code, filename="auth.py")
    print(result.score)          # 0-100
    print(result.summary())      # Rapport lisible
    print(result.passed)         # True si score >= seuil (défaut: 60)
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import List, Optional, Dict

# ── Critères extraits (REFACTO-01) — ré-exportés pour rétrocompat ────────────
from core.code_evaluator_criteria import (  # noqa: F401
    _CriteriaScorer,
    CriterionScore,
    _W_TYPE_HINTS,
    _W_DOCSTRINGS,
    _W_COMPLEXITY,
    _W_ANTIPATTERN,
)

# ──────────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_PASS_THRESHOLD = 60
_W_SYNTAX               = 30


# ──────────────────────────────────────────────────────────────────────────────
# EvaluationResult — résultat structuré
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EvaluationResult:
    """Résultat complet d'une évaluation de code."""
    filename:     str
    score:        int
    passed:       bool
    threshold:    int
    criteria:     List[CriterionScore] = field(default_factory=list)
    syntax_error: Optional[str]        = None
    n_functions:  int                  = 0
    n_classes:    int                  = 0
    n_lines:      int                  = 0
    complexity:   int                  = 0

    def summary(self) -> str:
        """Retourne un rapport lisible en une chaîne multilignes."""
        lines = [
            f"{'='*55}",
            f"  CodeEvaluator — {self.filename}",
            f"{'='*55}",
            f"  Score global : {self.score}/100  "
            f"({'✅ PASSED' if self.passed else '❌ FAILED'}, seuil={self.threshold})",
            f"  Lignes : {self.n_lines} | Fonctions : {self.n_functions} "
            f"| Classes : {self.n_classes} | Complexité : {self.complexity}",
            f"{'-'*55}",
        ]
        for c in self.criteria:
            bar = "█" * c.score + "░" * (c.max - c.score)
            lines.append(f"  {c.name:<22} {c.score:>3}/{c.max}  [{bar}]")
            if c.details:
                lines.append(f"    → {c.details}")
        if self.syntax_error:
            lines.append(f"  ⚠ Syntaxe : {self.syntax_error}")
        lines.append("=" * 55)
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        """Sérialisation dict (pour logs, JSON, etc.)."""
        return {
            "filename":     self.filename,
            "score":        self.score,
            "passed":       self.passed,
            "threshold":    self.threshold,
            "n_functions":  self.n_functions,
            "n_classes":    self.n_classes,
            "n_lines":      self.n_lines,
            "complexity":   self.complexity,
            "syntax_error": self.syntax_error,
            "criteria": [
                {"name": c.name, "score": c.score, "max": c.max, "details": c.details}
                for c in self.criteria
            ],
        }


# ──────────────────────────────────────────────────────────────────────────────
# CodeEvaluator — interface publique
# ──────────────────────────────────────────────────────────────────────────────

class CodeEvaluator:
    """
    Évalue la qualité statique d'un code Python généré.

    _CriteriaScorer est instancié une fois dans __init__ et délègue
    à code_evaluator_criteria.py (REFACTO-01).

    Le score est purement informatif en V1 — il n'empêche pas le patch.
    """

    def __init__(self, threshold: int = _DEFAULT_PASS_THRESHOLD) -> None:
        if not 0 <= threshold <= 100:
            raise ValueError(f"threshold doit être entre 0 et 100, reçu {threshold}")
        self.threshold = threshold
        self._scorer   = _CriteriaScorer()

    def evaluate(self, code: str, filename: str = "<generated>") -> EvaluationResult:
        """
        Évalue le code Python fourni.

        Args:
            code:     Code source Python (str).
            filename: Nom du fichier pour les messages d'erreur.

        Returns:
            EvaluationResult avec score total et détails par critère.
        """
        n_lines = len(code.splitlines())

        # ── 1. Syntaxe (bloquant) ─────────────────────────────────────────────
        try:
            tree = ast.parse(code, filename=filename)
        except SyntaxError as exc:
            syntax_err = f"{exc.msg} (ligne {exc.lineno})"
            return EvaluationResult(
                filename=filename,
                score=0,
                passed=False,
                threshold=self.threshold,
                syntax_error=syntax_err,
                n_lines=n_lines,
                criteria=[
                    CriterionScore(
                        name="Syntaxe Python",
                        score=0,
                        max=_W_SYNTAX,
                        details=f"Invalide : {syntax_err}",
                    )
                ],
            )

        syntax_crit = CriterionScore(
            name="Syntaxe Python", score=_W_SYNTAX, max=_W_SYNTAX, details="Valide",
        )

        # ── Métriques AST ─────────────────────────────────────────────────────
        n_functions = sum(
            1 for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        n_classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))

        # ── 2-5. Critères qualité ─────────────────────────────────────────────
        hints_crit               = self._scorer.score_type_hints(tree)
        doc_crit                 = self._scorer.score_docstrings(tree)
        complex_crit, complexity = self._scorer.score_complexity(tree)
        anti_crit                = self._scorer.score_antipatterns(tree, code)

        criteria = [syntax_crit, hints_crit, doc_crit, complex_crit, anti_crit]
        total    = sum(c.score for c in criteria)

        return EvaluationResult(
            filename=filename,
            score=total,
            passed=total >= self.threshold,
            threshold=self.threshold,
            criteria=criteria,
            syntax_error=None,
            n_functions=n_functions,
            n_classes=n_classes,
            n_lines=n_lines,
            complexity=complexity,
        )

    def evaluate_diff(
        self,
        before: str,
        after: str,
        filename: str = "<generated>",
    ) -> Dict:
        """Compare le score avant/après un patch."""
        r_before = self.evaluate(before, filename)
        r_after  = self.evaluate(after,  filename)
        delta    = r_after.score - r_before.score
        return {
            "filename":     filename,
            "score_before": r_before.score,
            "score_after":  r_after.score,
            "delta":        delta,
            "improved":     delta >= 0,
            "passed_after": r_after.passed,
            "result_after": r_after,
        }
