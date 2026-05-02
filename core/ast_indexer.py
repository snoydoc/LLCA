# -*- coding: utf-8-sig -*-
"""
ast_indexer.py — LCCA V5 Fusion
Sprint 03 — TASK-03-01 + TASK-03-02

Indexation des symboles Python d'un workspace via le module `ast` (lecture seule).
Retourne des dataclasses riches : Symbol, FileIndex, table de symboles cross-fichier.

Usage :
    indexer = ASTIndexer(workspace=Path("D:/LLMCodeAgent/workspace"))
    files = indexer.index_repository()
    syms  = indexer.symbols_table   # {"func_name": [Symbol, ...]}
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

log = logging.getLogger("lcca.ast_indexer")


# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Symbol:
    """Représente un symbole Python (fonction, classe, variable, import)."""
    name: str
    type: str                         # 'function' | 'class' | 'variable' | 'import'
    line: int
    file: str
    dependencies: Set[str] = field(default_factory=set)
    docstring: Optional[str] = None
    is_private: bool = False          # True si nom préfixé par '_'


@dataclass
class FileIndex:
    """Index complet d'un fichier Python."""
    path: str
    symbols: List[Symbol]
    imports: List[str]                # Modules importés
    exported: List[str]               # Noms définis au top-level
    raw_content: str
    size_bytes: int
    last_modified: float


# ──────────────────────────────────────────────────────────────────────────────
# Helpers AST internes
# ──────────────────────────────────────────────────────────────────────────────

def _collect_name_deps(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> Set[str]:
    """Collecte tous les ast.Name utilisés dans le corps d'une fonction."""
    deps: Set[str] = set()
    for child in ast.walk(func_node):
        if isinstance(child, ast.Name):
            deps.add(child.id)
    return deps


# ──────────────────────────────────────────────────────────────────────────────
# ASTIndexer
# ──────────────────────────────────────────────────────────────────────────────

class ASTIndexer:
    """
    Scanner de workspace Python.

    Attributes:
        workspace:      Dossier racine à scanner.
        files:          Dict[rel_path, FileIndex] après index_repository().
        symbols_table:  Dict[symbol_name, List[Symbol]] cross-fichier.
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace: Path = workspace
        self.files: Dict[str, FileIndex] = {}
        self.symbols_table: Dict[str, List[Symbol]] = {}

    # ── API publique ──────────────────────────────────────────────────────────

    def index_repository(self) -> Dict[str, FileIndex]:
        """
        Parcourt récursivement workspace/ et indexe tous les .py.
        Re-indexation idempotente (les résultats précédents sont écrasés).

        Returns:
            Dict {rel_path: FileIndex}
        """
        self.files.clear()
        self.symbols_table.clear()

        py_files = [
            f for f in self.workspace.rglob("*.py")
            if "__pycache__" not in str(f)
        ]

        log.info("Indexation de %d fichier(s) Python dans %s...", len(py_files), self.workspace)

        for py_file in sorted(py_files):
            try:
                idx = self._index_file(py_file)
                rel_path = str(py_file.relative_to(self.workspace))
                self.files[rel_path] = idx
                for sym in idx.symbols:
                    self.symbols_table.setdefault(sym.name, []).append(sym)
            except SyntaxError as e:
                log.warning("Syntaxe invalide, ignoré — %s: %s", py_file, e)
            except Exception as e:
                log.error("Erreur indexation %s: %s", py_file, e)

        self._resolve_cross_file_deps()
        log.info(
            "Index terminé : %d fichier(s), %d symbole(s) distincts.",
            len(self.files), len(self.symbols_table),
        )
        return self.files

    def _index_file(self, file_path: Path) -> FileIndex:
        """
        Indexe un seul fichier Python.

        Args:
            file_path: Chemin absolu vers le fichier .py.

        Returns:
            FileIndex avec symbols, imports, exported.

        Raises:
            SyntaxError: Si le fichier contient du Python invalide.
        """
        content = file_path.read_text(encoding="utf-8-sig")

        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError as e:
            raise SyntaxError(f"Syntaxe invalide dans {file_path}: {e}") from e

        symbols: List[Symbol] = []
        imports: List[str] = []
        exported: List[str] = []

        for node in tree.body:

            # ── Imports ───────────────────────────────────────────────────────
            if isinstance(node, ast.Import):
                # `import os` ou `import os.path`  → stocke le module racine
                for alias in node.names:
                    imports.append(alias.name)

            elif isinstance(node, ast.ImportFrom):
                # `from auth import authenticate`  → on dépend du MODULE "auth"
                # `from core.utils import fn`      → on dépend de "core.utils"
                # Règle : stocker le module (node.module), PAS "module.symbole".
                # Cela permet à DependencyGraph de retrouver "auth.py" directement.
                if node.module:
                    imports.append(node.module)
                # Cas `from . import something` (import relatif sans module explicite)
                else:
                    for alias in node.names:
                        imports.append(alias.name)

            # ── Fonctions top-level ───────────────────────────────────────────
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sym = Symbol(
                    name=node.name,
                    type="function",
                    line=node.lineno,
                    file=str(file_path),
                    is_private=node.name.startswith("_"),
                    docstring=ast.get_docstring(node),
                    dependencies=_collect_name_deps(node),
                )
                symbols.append(sym)
                exported.append(node.name)

            # ── Classes top-level ─────────────────────────────────────────────
            elif isinstance(node, ast.ClassDef):
                deps: Set[str] = set()
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        deps.add(base.id)
                    elif isinstance(base, ast.Attribute):
                        deps.add(base.attr)
                sym = Symbol(
                    name=node.name,
                    type="class",
                    line=node.lineno,
                    file=str(file_path),
                    is_private=node.name.startswith("_"),
                    docstring=ast.get_docstring(node),
                    dependencies=deps,
                )
                symbols.append(sym)
                exported.append(node.name)

            # ── Variables / constantes top-level ──────────────────────────────
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        sym = Symbol(
                            name=target.id,
                            type="variable",
                            line=node.lineno,
                            file=str(file_path),
                            is_private=target.id.startswith("_"),
                        )
                        symbols.append(sym)
                        exported.append(target.id)

            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    sym = Symbol(
                        name=node.target.id,
                        type="variable",
                        line=node.lineno,
                        file=str(file_path),
                        is_private=node.target.id.startswith("_"),
                    )
                    symbols.append(sym)
                    exported.append(node.target.id)

        stat = file_path.stat()
        return FileIndex(
            path=str(file_path),
            symbols=symbols,
            imports=imports,
            exported=exported,
            raw_content=content,
            size_bytes=stat.st_size,
            last_modified=stat.st_mtime,
        )

    # ── Résolution des dépendances cross-fichier ──────────────────────────────

    def _resolve_cross_file_deps(self) -> None:
        """
        Enrichit les dependencies des symboles avec les noms définis dans d'autres fichiers.
        Stratégie légère : si un nom dans dependencies correspond à un exported d'un autre fichier
        → dépendance confirmée.
        """
        all_exported: Set[str] = set()
        for fi in self.files.values():
            all_exported.update(fi.exported)

        for fi in self.files.values():
            for sym in fi.symbols:
                sym.dependencies &= all_exported  # Garde seulement les dépendances réelles
