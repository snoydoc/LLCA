# -*- coding: utf-8-sig -*-
"""
tests/test_ast_indexer.py — Sprint 03
Tests unitaires pour ASTIndexer + DependencyGraph.

Cible : 4/4 PASSED
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Ajuste le sys.path pour trouver core/ depuis tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.ast_indexer import ASTIndexer, Symbol, FileIndex
from core.dependency_graph import DependencyGraph


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """Workspace temporaire vide."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def write_py(workspace: Path, filename: str, content: str) -> Path:
    """Écrit un fichier .py dans le workspace et retourne son Path."""
    p = workspace / filename
    p.write_text(content, encoding="utf-8-sig")
    return p


# ──────────────────────────────────────────────────────────────────────────────
# TESTS
# ──────────────────────────────────────────────────────────────────────────────

def test_index_simple_file(tmp_workspace: Path) -> None:
    """Indexe un fichier avec 1 classe et 2 fonctions."""
    src = '''\
class MyModel:
    """A model."""
    pass

def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello {name}"

def _private_helper() -> None:
    pass
'''
    p = write_py(tmp_workspace, "module_a.py", src)
    indexer = ASTIndexer(workspace=tmp_workspace)
    fi = indexer._index_file(p)

    assert isinstance(fi, FileIndex)

    names = {s.name for s in fi.symbols}
    assert "MyModel" in names
    assert "greet" in names
    assert "_private_helper" in names

    # Types corrects
    types = {s.name: s.type for s in fi.symbols}
    assert types["MyModel"] == "class"
    assert types["greet"] == "function"

    # Exports
    assert "MyModel" in fi.exported
    assert "greet" in fi.exported


def test_symbol_with_docstring(tmp_workspace: Path) -> None:
    """Docstring extraite correctement pour fonctions et classes."""
    src = '''\
def documented() -> None:
    """This is the docstring."""
    pass

class WithDoc:
    """Class docstring."""
    pass

def no_doc() -> None:
    pass
'''
    p = write_py(tmp_workspace, "docs.py", src)
    indexer = ASTIndexer(workspace=tmp_workspace)
    fi = indexer._index_file(p)

    by_name = {s.name: s for s in fi.symbols}

    assert by_name["documented"].docstring == "This is the docstring."
    assert by_name["WithDoc"].docstring == "Class docstring."
    assert by_name["no_doc"].docstring is None

    # Privé
    src2 = "def _helper(): pass\n"
    p2 = write_py(tmp_workspace, "priv.py", src2)
    fi2 = indexer._index_file(p2)
    assert fi2.symbols[0].is_private is True


def test_syntax_error_ignored(tmp_workspace: Path) -> None:
    """Un fichier avec syntaxe invalide est ignoré dans index_repository(), sans crash."""
    # Fichier valide
    write_py(tmp_workspace, "good.py", "def ok(): pass\n")
    # Fichier invalide
    write_py(tmp_workspace, "bad.py", "def broken(:\n    pass\n")

    indexer = ASTIndexer(workspace=tmp_workspace)
    files = indexer.index_repository()

    # Le fichier invalide ne doit pas apparaître dans l'index
    assert any("good.py" in k for k in files)
    assert not any("bad.py" in k for k in files)

    # _index_file direct doit lever SyntaxError
    bad_path = tmp_workspace / "bad.py"
    with pytest.raises(SyntaxError):
        indexer._index_file(bad_path)


def test_cross_file_dependency(tmp_workspace: Path) -> None:
    """B importe A → dépendance détectée dans le graphe."""
    write_py(tmp_workspace, "auth.py", "def authenticate(user): pass\n")
    write_py(tmp_workspace, "views.py", "from auth import authenticate\ndef login(): authenticate('x')\n")

    indexer = ASTIndexer(workspace=tmp_workspace)
    files = indexer.index_repository()

    graph = DependencyGraph()
    graph.build(files)

    # views.py dépend de auth.py
    deps = graph.get_dependencies("views.py")
    assert "auth.py" in deps

    # auth.py a views.py comme dependent
    dependents = graph.get_dependents("auth.py")
    assert "views.py" in dependents

    # impact_radius de auth.py inclut views.py
    impact = graph.get_impact_radius("auth.py", depth=2)
    assert "views.py" in impact


def test_index_repository_empty(tmp_workspace: Path) -> None:
    """Workspace vide → index vide, pas d'erreur."""
    indexer = ASTIndexer(workspace=tmp_workspace)
    files = indexer.index_repository()
    assert files == {}
    assert indexer.symbols_table == {}


def test_index_repository_idempotent(tmp_workspace: Path) -> None:
    """Re-indexation idempotente : 2 appels successifs = même résultat."""
    write_py(tmp_workspace, "mod.py", "def foo(): pass\n")
    indexer = ASTIndexer(workspace=tmp_workspace)
    result1 = indexer.index_repository()
    result2 = indexer.index_repository()
    assert list(result1.keys()) == list(result2.keys())
