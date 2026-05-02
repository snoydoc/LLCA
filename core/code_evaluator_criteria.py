# -*- coding: utf-8-sig -*-
"""
code_evaluator_criteria.py — Critères de scoring pour CodeEvaluator (Sprint REFACTO-01).

Extrait de code_evaluator.py pour réduire sa taille de 18.4 KB à ~5 KB.
Contient CriterionScore (dataclass) + _CriteriaScorer (5 méthodes de scoring stateless).

Importé par code_evaluator.py :
    from core.code_evaluator_criteria import _CriteriaScorer, CriterionScore
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import List

# Poids des critères — synchronisés avec code_evaluator.py
# Note : _W_SYNTAX (30 pts) est défini dans code_evaluator.py et géré par CodeEvaluator.
# Ce module ne gère que les critères 2-5 (type hints, docstrings, complexité, anti-patterns).
_W_TYPE_HINTS   = 20
_W_DOCSTRINGS   = 20
_W_COMPLEXITY   = 15
_W_ANTIPATTERN  = 15
_MAX_COMPLEXITY = 10


# ──────────────────────────────────────────────────────────────────────────────
# CriterionScore — score d'un critère individuel (publié depuis ce module)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CriterionScore:
    """Score d'un critère individuel d'évaluation de code."""
    name:    str
    score:   int    # Points obtenus
    max:     int    # Points possibles
    details: str    # Explication courte


# ──────────────────────────────────────────────────────────────────────────────
# _CriteriaScorer — calcul par critère
# ──────────────────────────────────────────────────────────────────────────────

class _CriteriaScorer:
    """
    Calcule les scores individuels à partir d'un AST déjà parsé.
    Toutes les méthodes sont stateless et prennent le tree en argument.
    Instancié par CodeEvaluator dans son __init__.
    """

    # ── 1. Type hints ─────────────────────────────────────────────────────────

    @staticmethod
    def score_type_hints(tree: ast.Module) -> CriterionScore:
        """
        Vérifie la présence de type hints sur les fonctions/méthodes.
        Score proportionnel : (fonctions avec hints complets) / (total fonctions).
        """
        funcs = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if not funcs:
            return CriterionScore(
                name="Type hints",
                score=_W_TYPE_HINTS,
                max=_W_TYPE_HINTS,
                details="Aucune fonction — critère non applicable (bonus accordé)",
            )

        fully_typed = 0
        partially_typed = 0
        for fn in funcs:
            has_return   = fn.returns is not None
            args         = [a for a in fn.args.args if a.arg not in ("self", "cls")]
            n_annotated  = sum(1 for a in args if a.annotation is not None)
            n_args       = len(args)

            if has_return and (n_args == 0 or n_annotated == n_args):
                fully_typed += 1
            elif has_return or n_annotated > 0:
                partially_typed += 1

        ratio_full    = fully_typed    / len(funcs)
        ratio_partial = partially_typed / len(funcs)
        score = min(int(_W_TYPE_HINTS * (ratio_full + ratio_partial * 0.5)), _W_TYPE_HINTS)
        detail = (
            f"{fully_typed}/{len(funcs)} fonction(s) complètement typée(s), "
            f"{partially_typed} partiellement"
        )
        return CriterionScore(name="Type hints", score=score, max=_W_TYPE_HINTS, details=detail)

    # ── 2. Docstrings ─────────────────────────────────────────────────────────

    @staticmethod
    def score_docstrings(tree: ast.Module) -> CriterionScore:
        """
        Vérifie la présence de docstrings sur le module et les def/class.
        Score proportionnel : entités avec docstring / total entités.
        """
        has_module_doc = (
            isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ) if tree.body else False

        entities = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]

        if not entities and not has_module_doc:
            return CriterionScore(
                name="Docstrings",
                score=_W_DOCSTRINGS // 2,
                max=_W_DOCSTRINGS,
                details="Aucune entité documentable trouvée",
            )

        with_doc = sum(
            1 for n in entities
            if (
                n.body
                and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)
                and isinstance(n.body[0].value.value, str)
            )
        )
        total  = len(entities) + (1 if has_module_doc else 0)
        found  = with_doc + (1 if has_module_doc else 0)
        ratio  = found / total if total else 0
        score  = int(_W_DOCSTRINGS * ratio)
        detail = (
            f"{found}/{total} entité(s) documentée(s)"
            f"{' (module inclus)' if has_module_doc else ''}"
        )
        return CriterionScore(name="Docstrings", score=score, max=_W_DOCSTRINGS, details=detail)

    # ── 3. Complexité cyclomatique ────────────────────────────────────────────

    @staticmethod
    def score_complexity(tree: ast.Module) -> tuple:
        """
        Estime la complexité cyclomatique totale (McCabe simplifié).
        Retourne (CriterionScore, complexité_brute).
        """
        _BRANCH_NODES = (
            ast.If, ast.For, ast.AsyncFor, ast.While,
            ast.ExceptHandler, ast.With, ast.AsyncWith,
            ast.Assert,
        )
        complexity = 1
        for node in ast.walk(tree):
            if isinstance(node, _BRANCH_NODES):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1

        if complexity <= 3:
            score  = _W_COMPLEXITY
            detail = f"Complexité {complexity} — excellent (≤3)"
        elif complexity <= 6:
            ratio  = 1.0 - (complexity - 3) / (6 - 3) * 0.4
            score  = int(_W_COMPLEXITY * ratio)
            detail = f"Complexité {complexity} — acceptable (4-6)"
        elif complexity <= _MAX_COMPLEXITY:
            ratio  = 1.0 - (complexity - 6) / (_MAX_COMPLEXITY - 6) * 0.7
            score  = max(int(_W_COMPLEXITY * ratio), 2)
            detail = f"Complexité {complexity} — élevée (7-{_MAX_COMPLEXITY})"
        else:
            score  = 0
            detail = f"Complexité {complexity} — trop élevée (>{_MAX_COMPLEXITY})"

        return CriterionScore(
            name="Complexité cyclom.", score=score, max=_W_COMPLEXITY, details=detail,
        ), complexity

    # ── 4. Anti-patterns ─────────────────────────────────────────────────────

    @staticmethod
    def score_antipatterns(tree: ast.Module, source: str) -> CriterionScore:
        """
        Détecte des anti-patterns courants dans le code.

        Pénalités :
          - bare except:        → -5 pts
          - print(              → -3 pts
          - global déclaré      → -4 pts
          - eval() / exec()     → -5 pts
          - import *            → -3 pts
        """
        issues: List[str] = []
        deductions = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append("bare `except:` sans type")
                deductions += 5
            if isinstance(node, ast.Global):
                issues.append(f"`global {', '.join(node.names)}`")
                deductions += 4
            if isinstance(node, ast.ImportFrom) and any(
                a.name == "*" for a in node.names
            ):
                issues.append(f"`from {node.module} import *`")
                deductions += 3

        if re.search(r"\bprint\s*\(", source):
            issues.append("`print()` dans le code")
            deductions += 3
        if re.search(r"\b(eval|exec)\s*\(", source):
            issues.append("`eval()`/`exec()` détecté")
            deductions += 5

        score  = max(_W_ANTIPATTERN - deductions, 0)
        detail = (
            f"{len(issues)} anti-pattern(s) : {'; '.join(issues)}"
            if issues else "Aucun anti-pattern détecté"
        )
        return CriterionScore(name="Anti-patterns", score=score, max=_W_ANTIPATTERN, details=detail)
