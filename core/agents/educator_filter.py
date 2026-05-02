# -*- coding: utf-8-sig -*-
"""
educator_filter.py -- EducatorAgent V9.1 -- Couche filtrage LCCA

Responsabilite unique : 7 regles de filtrage qualite du code Python.
Sans dependance reseau ni memoire.

Extrait de educator_agent.py (REFACTO-02, 2026-04-21).
"""
from __future__ import annotations

import ast
import logging
import sys
from typing import Optional

log = logging.getLogger("lcca.educator.filter")


class EducatorFilter:
    """
    Applique les 7 regles LCCA a un snippet de code Python.

    Regles :
        R1 : type hints (detection AST)
        R2 : docstrings (guillemets triples)
        R3 : pas de "python" hardcode
        R4 : pas de print() hors bloc __main__
        R5 : taille raisonnable (< 300 lignes)
        R6 : pas de shell=True
        R7 : pathlib/os si le fichier manipule des chemins

    Score minimum configurable via min_filter_score.
    CodeEvaluator injecte en option pour le scoring final.
    """

    def __init__(
        self,
        min_filter_score : int = 5,
        min_score        : int = 70,
        evaluator        = None,
    ) -> None:
        self._min_filter_score = min_filter_score
        self._min_score        = min_score
        self._evaluator        = evaluator

    # -------------------------------------------------------------------------
    # Filtre principal
    # -------------------------------------------------------------------------

    def passes(self, src: str) -> bool:
        """
        Retourne True si src passe les 7 regles + evaluateur.

        Les 7 regles donnent un score sur 7 ; si score < min_filter_score,
        le snippet est rejete avant meme d'appeler CodeEvaluator.
        """
        score = 0

        if self.has_type_hints(src):
            score += 1
        if '"""' in src or "'''" in src:
            score += 1
        if '"python"' not in src and "'python'" not in src:
            score += 1
        if not self.has_bad_print(src):
            score += 1
        if src.count("\n") < 300:
            score += 1
        if "shell=True" not in src:
            score += 1
        if self.pathlib_rule(src):
            score += 1

        if score < self._min_filter_score:
            return False

        if self._evaluator is not None:
            try:
                ev = self._evaluator.evaluate(src)
                return ev.score >= self._min_score
            except Exception:
                return False
        return True

    # -------------------------------------------------------------------------
    # Regles individuelles (publiques pour tests unitaires)
    # -------------------------------------------------------------------------

    def has_type_hints(self, src: str) -> bool:
        """R1 : Detecte les type hints via AST (annotations args ou return)."""
        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.returns or any(a.annotation for a in node.args.args):
                        return True
        except SyntaxError:
            return "->" in src  # fallback texte
        return False

    def has_bad_print(self, src: str) -> bool:
        """R4 : True si print() est utilise hors d'un bloc if __name__ == '__main__'."""
        if "print(" not in src:
            return False
        in_main = False
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("if __name__"):
                in_main = True
            if not in_main and "print(" in stripped and not stripped.startswith("#"):
                return True
        return False

    def pathlib_rule(self, src: str) -> bool:
        """
        R7 : N'exige pathlib/os que si le fichier utilise open() ou des chemins.
        Assouplie (P0) : fichier sans I/O -> regle satisfaite d'office.
        """
        needs_path = "open(" in src or "os.path" in src or "Path(" in src
        if not needs_path:
            return True
        return "from pathlib" in src or "import os" in src or "import pathlib" in src
