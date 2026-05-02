# -*- coding: utf-8-sig -*-
"""
dependency_graph.py — LCCA V5 Fusion
Sprint 03 — TASK-03-03

Graphe orienté de dépendances entre fichiers Python.
Permet de répondre à : "Si je modifie auth.py, quels fichiers sont impactés ?"

Usage :
    graph = DependencyGraph()
    graph.build(indexer.files)
    impacted = graph.get_impact_radius("auth.py", depth=2)
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Dict, List, Set

from .ast_indexer import FileIndex

log = logging.getLogger("lcca.dependency_graph")


class DependencyGraph:
    """
    Graphe orienté de dépendances inter-fichiers.

    Nœuds  : chemins relatifs des fichiers (.py)
    Arêtes : A → B  signifie "A importe B" (A dépend de B)

    Attributes:
        _deps:       Dict[file, List[dep]]  — fichiers dont file dépend
        _dependents: Dict[file, List[dep]]  — fichiers qui importent file
    """

    def __init__(self) -> None:
        self._deps:       Dict[str, List[str]] = {}
        self._dependents: Dict[str, List[str]] = {}

    # ── Construction ──────────────────────────────────────────────────────────

    def build(self, files: Dict[str, FileIndex]) -> None:
        """
        Construit le graphe depuis l'index produit par ASTIndexer.

        Stratégie de résolution des imports :
          - L'import "auth" ou "core.auth" est associé au fichier "auth.py"
            ou "core/auth.py" si présent dans files.
        """
        self._deps.clear()
        self._dependents.clear()

        # Initialise tous les nœuds
        for rel_path in files:
            self._deps.setdefault(rel_path, [])
            self._dependents.setdefault(rel_path, [])

        # Construit les arêtes
        for rel_path, fi in files.items():
            for import_str in fi.imports:
                # Convertit "core.auth" → "core/auth.py" (chemin relatif)
                candidate = import_str.replace(".", "/") + ".py"
                if candidate in files and candidate != rel_path:
                    self._add_edge(rel_path, candidate)
                    continue
                # Essai avec juste le dernier segment: "auth" → "auth.py"
                short = import_str.split(".")[-1] + ".py"
                if short in files and short != rel_path:
                    self._add_edge(rel_path, short)

        self._detect_cycles()

    def _add_edge(self, src: str, dst: str) -> None:
        """Ajoute src → dst (src dépend de dst) sans doublon."""
        if dst not in self._deps[src]:
            self._deps[src].append(dst)
        if src not in self._dependents[dst]:
            self._dependents[dst].append(src)

    # ── Requêtes ──────────────────────────────────────────────────────────────

    def get_dependencies(self, file_path: str) -> List[str]:
        """Retourne les fichiers dont file_path dépend (imports directs)."""
        return list(self._deps.get(file_path, []))

    def get_dependents(self, file_path: str) -> List[str]:
        """Retourne les fichiers qui importent file_path."""
        return list(self._dependents.get(file_path, []))

    def get_impact_radius(self, file_path: str, depth: int = 2) -> Set[str]:
        """
        Retourne l'ensemble des fichiers impactés par une modification de file_path.
        Utilise un BFS sur le graphe inversé (dependents) jusqu'à `depth` niveaux.

        Args:
            file_path: Fichier modifié (chemin relatif).
            depth:     Profondeur max de propagation (défaut 2).

        Returns:
            Set des fichiers impactés (n'inclut pas file_path lui-même).
        """
        visited: Set[str] = set()
        queue: deque[tuple[str, int]] = deque([(file_path, 0)])

        while queue:
            current, level = queue.popleft()
            if level >= depth:
                continue
            for dependent in self._dependents.get(current, []):
                if dependent not in visited:
                    visited.add(dependent)
                    queue.append((dependent, level + 1))

        visited.discard(file_path)
        return visited

    # ── Détection de cycles ───────────────────────────────────────────────────

    def _detect_cycles(self) -> None:
        """Détecte les cycles dans le graphe et les loggue (sans crash)."""
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for dep in self._deps.get(node, []):
                if dep not in visited:
                    if dfs(dep):
                        return True
                elif dep in rec_stack:
                    log.warning("Cycle de dépendances détecté: %s → %s", node, dep)
                    return True
            rec_stack.discard(node)
            return False

        for node in list(self._deps.keys()):
            if node not in visited:
                dfs(node)

    # ── Sérialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, List[str]]:
        """Sérialise le graphe (deps) en dictionnaire JSON-compatible."""
        return {k: list(v) for k, v in self._deps.items()}

    def to_json(self) -> str:
        """Retourne la représentation JSON du graphe."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
