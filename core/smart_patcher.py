# -*- coding: utf-8-sig -*-
"""
smart_patcher.py — LCCA V5 Fusion
Sprint 03 — TASK-03-04 / 05 / 06 / 07
Sprint REFACTO-01 — Transformers extraits dans smart_patcher_transformers.py.
                    Rétrocompat : AddFunctionTransformer, ModifyFunctionTransformer,
                    AddImportTransformer restent importables depuis ce module.

Modification chirurgicale de code Python via libcst (transformers AST).
⚠️  Jamais de manipulation de texte brut, jamais de regex.

API publique (SmartPatcher) :
    apply_patch(file_path, patch_type, **kwargs) → str   (nouveau contenu)
    add_function(path, func_code)                → str
    modify_function(path, func_name, new_body)   → str
    add_import(path, module, names=None)         → str
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

try:
    import libcst as cst
    _LIBCST_AVAILABLE = True
except ImportError:
    _LIBCST_AVAILABLE = False

log = logging.getLogger("lcca.smart_patcher")

# ── Transformers extraits (REFACTO-01) — ré-exportés pour rétrocompat ─────────
if _LIBCST_AVAILABLE:
    from core.smart_patcher_transformers import (  # noqa: F401
        AddFunctionTransformer,
        ModifyFunctionTransformer,
        AddImportTransformer,
    )


# ──────────────────────────────────────────────────────────────────────────────
# TASK-03-07 : SmartPatcher — Interface générique
# ──────────────────────────────────────────────────────────────────────────────

class SmartPatcher:
    """
    Applique des patches AST chirurgicaux sur des fichiers Python.

    ⚠️  Cette classe NE MODIFIE PAS les fichiers elle-même.
        Elle retourne le nouveau contenu en string.
        C'est le TransactionManager qui gère l'écriture (ACID).

    Les transformers (AddFunctionTransformer, ModifyFunctionTransformer,
    AddImportTransformer) sont définis dans smart_patcher_transformers.py
    et ré-exportés ici pour rétrocompatibilité.
    """

    def __init__(self, workspace: Optional[Path] = None) -> None:
        self.workspace = workspace or Path("D:/LLMCodeAgent/workspace")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8-sig")

    @staticmethod
    def _validate_syntax(source: str, label: str = "") -> None:
        """Lève SyntaxError si le source Python est invalide."""
        compile(source, label or "<string>", "exec")

    # ── apply_patch() — Interface générique (TASK-03-07) ─────────────────────

    def apply_patch(self, file_path: str, patch_type: str, **kwargs) -> str:
        """
        Interface haut niveau. Retourne le nouveau contenu (ne l'écrit PAS).
        Compatible avec TransactionManager.log_operation().

        Args:
            file_path:  Chemin relatif depuis workspace (ex: "auth.py")
            patch_type: "add_function" | "modify_function" | "add_import"
            **kwargs:
                add_function    → code: str
                modify_function → name: str, code: str, preserve_docstring: bool = True
                add_import      → module: str, names: Optional[List[str]]

        Returns:
            str: Contenu Python modifié (syntaxe validée avant ET après).

        Raises:
            SyntaxError:  Si source ou résultat invalide.
            ValueError:   Si patch_type inconnu ou fonction introuvable.
            ImportError:  Si libcst non installé.
        """
        if not _LIBCST_AVAILABLE:
            raise ImportError(
                "libcst est requis pour SmartPatcher. "
                "Installez-le : pip install libcst"
            )

        path   = self.workspace / file_path
        source = self._read(path)

        self._validate_syntax(source, file_path)
        tree = cst.parse_module(source)

        if patch_type == "add_function":
            if "code" not in kwargs:
                raise ValueError("apply_patch 'add_function' requiert le kwarg 'code'")
            transformer = AddFunctionTransformer(kwargs["code"])

        elif patch_type == "modify_function":
            if "name" not in kwargs or "code" not in kwargs:
                raise ValueError(
                    "apply_patch 'modify_function' requiert les kwargs 'name' et 'code'"
                )
            transformer = ModifyFunctionTransformer(
                target_name=kwargs["name"],
                new_body_code=kwargs["code"],
                preserve_docstring=kwargs.get("preserve_docstring", True),
            )

        elif patch_type == "add_import":
            if "module" not in kwargs:
                raise ValueError("apply_patch 'add_import' requiert le kwarg 'module'")
            transformer = AddImportTransformer(
                module=kwargs["module"],
                names=kwargs.get("names"),
            )

        else:
            raise ValueError(
                f"Type de patch inconnu: '{patch_type}'. "
                "Valeurs valides: 'add_function', 'modify_function', 'add_import'"
            )

        new_tree = tree.visit(transformer)
        new_code = new_tree.code

        self._validate_syntax(new_code, f"{file_path} [après patch]")
        log.debug(
            "Patch '%s' appliqué sur %s (%d → %d chars)",
            patch_type, file_path, len(source), len(new_code),
        )
        return new_code

    # ── Méthodes de commodité ─────────────────────────────────────────────────

    def add_function(self, path: Path, func_code: str) -> str:
        """Ajoute func_code à la fin du fichier. Retourne le contenu modifié."""
        source = self._read(path)
        self._validate_syntax(func_code, "<new_function>")
        self._validate_syntax(source, str(path))
        tree     = cst.parse_module(source)
        new_tree = tree.visit(AddFunctionTransformer(func_code))
        result   = new_tree.code
        self._validate_syntax(result, str(path))
        return result

    def modify_function(
        self,
        path: Path,
        func_name: str,
        new_body_code: str,
        preserve_docstring: bool = True,
    ) -> str:
        """Remplace le corps de func_name. Retourne le contenu modifié."""
        source      = self._read(path)
        self._validate_syntax(source, str(path))
        tree        = cst.parse_module(source)
        transformer = ModifyFunctionTransformer(func_name, new_body_code, preserve_docstring)
        new_tree    = tree.visit(transformer)
        if not transformer.modified:
            raise ValueError(
                f"Fonction '{func_name}' introuvable dans {path}. "
                "Vérifiez le nom et l'indentation."
            )
        result = new_tree.code
        self._validate_syntax(result, str(path))
        return result

    def add_import(
        self,
        path: Path,
        module: str,
        names: Optional[List[str]] = None,
    ) -> str:
        """Ajoute un import en tête du fichier. Retourne le contenu modifié."""
        source   = self._read(path)
        self._validate_syntax(source, str(path))
        tree     = cst.parse_module(source)
        new_tree = tree.visit(AddImportTransformer(module, names))
        result   = new_tree.code
        self._validate_syntax(result, str(path))
        return result
