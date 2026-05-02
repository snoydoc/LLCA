# -*- coding: utf-8-sig -*-
"""
tests/test_smart_patcher.py — Sprint 03
Tests unitaires pour SmartPatcher (AddFunction, ModifyFunction, AddImport).

Cible : 6/6 PASSED
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.smart_patcher import SmartPatcher

try:
    import libcst as cst
    _LIBCST_AVAILABLE = True
except ImportError:
    _LIBCST_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _LIBCST_AVAILABLE,
    reason="libcst non disponible"
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def patcher(workspace: Path) -> SmartPatcher:
    return SmartPatcher(workspace=workspace)


def make_file(workspace: Path, name: str, content: str) -> Path:
    p = workspace / name
    p.write_text(content, encoding="utf-8-sig")
    return p


# ──────────────────────────────────────────────────────────────────────────────
# TESTS AddFunction
# ──────────────────────────────────────────────────────────────────────────────

def test_add_function_appended(patcher: SmartPatcher, workspace: Path) -> None:
    """La nouvelle fonction est ajoutée à la fin du module."""
    src = "def existing(): pass\n"
    make_file(workspace, "mod.py", src)

    new_func = "def new_func(x: int) -> int:\n    return x * 2\n"
    result = patcher.apply_patch("mod.py", "add_function", code=new_func)

    assert "def existing" in result
    assert "def new_func" in result
    # new_func doit apparaître APRÈS existing
    assert result.index("def new_func") > result.index("def existing")


def test_add_function_pep8_spacing(patcher: SmartPatcher, workspace: Path) -> None:
    """2 lignes vides avant la nouvelle fonction (PEP8 E302)."""
    src = "def first(): pass\n"
    make_file(workspace, "mod.py", src)

    new_func = "def second(): pass\n"
    result = patcher.apply_patch("mod.py", "add_function", code=new_func)

    # Il doit y avoir au moins 2 lignes vides avant 'def second'
    idx_second = result.index("def second")
    before = result[:idx_second]
    # Compte les newlines consécutifs à la fin du bloc avant
    assert before.endswith("\n\n") or before.endswith("\n\n\n"), (
        f"Pas assez de lignes vides avant 'def second'. Avant:\n{repr(before[-20:])}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# TESTS ModifyFunction
# ──────────────────────────────────────────────────────────────────────────────

def test_modify_preserves_signature(patcher: SmartPatcher, workspace: Path) -> None:
    """Signature (params, return type) inchangée après modification du corps."""
    src = '''\
def compute(x: int, y: int) -> int:
    return x + y
'''
    make_file(workspace, "mod.py", src)

    new_body = "    return x * y\n"
    result = patcher.apply_patch(
        "mod.py", "modify_function", name="compute", code=new_body
    )

    assert "def compute(x: int, y: int) -> int:" in result
    assert "return x * y" in result
    assert "return x + y" not in result


def test_modify_preserves_docstring(patcher: SmartPatcher, workspace: Path) -> None:
    """Docstring préservée quand preserve_docstring=True (défaut)."""
    src = '''\
def greet(name: str) -> str:
    """Return a greeting."""
    return "hello"
'''
    make_file(workspace, "mod.py", src)

    new_body = '    return f"Hi {name}!"\n'
    result = patcher.apply_patch(
        "mod.py", "modify_function",
        name="greet", code=new_body, preserve_docstring=True
    )

    assert '"""Return a greeting."""' in result
    assert 'return f"Hi {name}!"' in result
    assert 'return "hello"' not in result


# ──────────────────────────────────────────────────────────────────────────────
# TESTS AddImport
# ──────────────────────────────────────────────────────────────────────────────

def test_no_duplicate_import(patcher: SmartPatcher, workspace: Path) -> None:
    """Import déjà présent → pas de doublon dans le résultat."""
    src = "import os\n\ndef foo(): pass\n"
    make_file(workspace, "mod.py", src)

    result = patcher.apply_patch("mod.py", "add_import", module="os")

    # "import os" ne doit apparaître qu'une seule fois
    assert result.count("import os") == 1


def test_add_import_inserted(patcher: SmartPatcher, workspace: Path) -> None:
    """Import absent → ajouté dans le fichier."""
    src = "def foo(): pass\n"
    make_file(workspace, "mod.py", src)

    result = patcher.apply_patch("mod.py", "add_import", module="pathlib", names=["Path"])

    assert "from pathlib import Path" in result
    # L'import doit précéder la définition de fonction
    assert result.index("from pathlib") < result.index("def foo")


# ──────────────────────────────────────────────────────────────────────────────
# TEST Sécurité : code invalide → SyntaxError avant toute écriture
# ──────────────────────────────────────────────────────────────────────────────

def test_invalid_code_raises_before_write(patcher: SmartPatcher, workspace: Path) -> None:
    """Code invalide → SyntaxError levée, fichier source inchangé."""
    src = "def valid(): pass\n"
    p = make_file(workspace, "mod.py", src)
    original_content = p.read_text(encoding="utf-8-sig")

    invalid_func = "def broken(:\n    pass\n"

    with pytest.raises(SyntaxError):
        patcher.apply_patch("mod.py", "add_function", code=invalid_func)

    # Le fichier sur disque ne doit pas avoir changé
    assert p.read_text(encoding="utf-8-sig") == original_content
