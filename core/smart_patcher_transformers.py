# -*- coding: utf-8-sig -*-
"""
smart_patcher_transformers.py — Transformers libcst pour SmartPatcher (Sprint REFACTO-01).

Contient les 3 classes CSTTransformer extraites de smart_patcher.py :
    AddFunctionTransformer     — Ajoute une fonction en fin de module
    ModifyFunctionTransformer  — Remplace le corps d'une fonction existante
    AddImportTransformer       — Ajoute un import sans doublon

N'est importé que si libcst est disponible (_LIBCST_AVAILABLE = True dans smart_patcher.py).
Si libcst absent : ce fichier n'est pas importé, SmartPatcher utilise le fallback texte.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

import libcst as cst

log = logging.getLogger("lcca.smart_patcher_transformers")


# ──────────────────────────────────────────────────────────────────────────────
# AddFunctionTransformer
# ──────────────────────────────────────────────────────────────────────────────

class AddFunctionTransformer(cst.CSTTransformer):
    """
    Ajoute une ou plusieurs fonctions à la fin du module.
    Insère 2 lignes vides avant la nouvelle fonction (PEP 8 E302).
    """

    def __init__(self, func_code: str) -> None:
        try:
            cst.parse_module(func_code)
        except cst.ParserSyntaxError as e:
            raise SyntaxError(f"Code à injecter invalide: {e}") from e
        self._func_code = func_code
        self._added = False

    def leave_Module(
        self,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
        if self._added:
            return updated_node

        new_module = cst.parse_module(self._func_code)

        new_stmts = list(new_module.body)
        if new_stmts:
            first = new_stmts[0]
            existing_leading = list(getattr(first, "leading_lines", []))
            blank_lines = [cst.EmptyLine(), cst.EmptyLine()]
            new_stmts[0] = first.with_changes(  # type: ignore[union-attr]
                leading_lines=blank_lines + existing_leading
            )

        new_body = list(updated_node.body) + new_stmts
        self._added = True
        return updated_node.with_changes(body=new_body)


# ──────────────────────────────────────────────────────────────────────────────
# ModifyFunctionTransformer
# ──────────────────────────────────────────────────────────────────────────────

class ModifyFunctionTransformer(cst.CSTTransformer):
    """
    Remplace le corps d'une fonction existante.
    Préserve : signature, décorateurs, type hints, docstring (si preserve_docstring=True).
    """

    def __init__(
        self,
        target_name: str,
        new_body_code: str,
        preserve_docstring: bool = True,
    ) -> None:
        self.target_name = target_name
        self.new_body_code = new_body_code
        self.preserve_docstring = preserve_docstring
        self.modified = False

    @staticmethod
    def _indent(code: str, spaces: int = 4) -> str:
        return "\n".join(" " * spaces + line for line in code.splitlines())

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> cst.FunctionDef:
        if original_node.name.value != self.target_name or self.modified:
            return updated_node

        wrapper = f"def _tmp_():\n{self._indent(self.new_body_code)}\n"
        try:
            tmp_module = cst.parse_module(wrapper)
        except cst.ParserSyntaxError as e:
            raise SyntaxError(
                f"Nouveau corps pour '{self.target_name}' invalide: {e}"
            ) from e

        tmp_func = tmp_module.body[0]
        new_body: cst.IndentedBlock = tmp_func.body  # type: ignore[union-attr]

        if self.preserve_docstring:
            orig_body = original_node.body
            if (
                orig_body.body
                and isinstance(orig_body.body[0], cst.SimpleStatementLine)
                and isinstance(orig_body.body[0].body[0], cst.Expr)
                and isinstance(
                    orig_body.body[0].body[0].value,
                    (cst.SimpleString, cst.ConcatenatedString, cst.FormattedString),
                )
            ):
                docstring_stmt = orig_body.body[0]
                new_body = new_body.with_changes(
                    body=[docstring_stmt, *list(new_body.body)]
                )

        self.modified = True
        return updated_node.with_changes(body=new_body)


# ──────────────────────────────────────────────────────────────────────────────
# AddImportTransformer
# ──────────────────────────────────────────────────────────────────────────────

class AddImportTransformer(cst.CSTTransformer):
    """
    Ajoute un import en tête de module sans créer de doublon.
    Supporte :
      - import module
      - from module import name1, name2
    Placement : après from __future__ import ... et la docstring module.
    """

    def __init__(self, module: str, names: Optional[Sequence[str]] = None) -> None:
        self._module = module
        self._names = list(names) if names else None
        self._already_present = False
        self._insert_index = 0

    def _build_import_node(self) -> cst.SimpleStatementLine:
        if self._names:
            stmt_code = f"from {self._module} import {', '.join(self._names)}\n"
        else:
            stmt_code = f"import {self._module}\n"
        return cst.parse_statement(stmt_code)  # type: ignore[return-value]

    def _import_matches(self, node: cst.BaseStatement) -> bool:
        try:
            if isinstance(node, cst.SimpleStatementLine):
                for stmt in node.body:
                    if self._names and isinstance(stmt, cst.ImportFrom):
                        mod_name = self._extract_module_name(stmt.module) if stmt.module else ""
                        if mod_name == self._module:
                            if isinstance(stmt.names, (list, tuple)):
                                existing = {
                                    a.name.value  # type: ignore[union-attr]
                                    for a in stmt.names
                                    if hasattr(a.name, "value")
                                }
                                if all(n in existing for n in (self._names or [])):
                                    return True
                    elif not self._names and isinstance(stmt, cst.Import):
                        if isinstance(stmt.names, (list, tuple)):
                            for alias in stmt.names:
                                if (
                                    hasattr(alias, "name")
                                    and hasattr(alias.name, "value")
                                    and alias.name.value == self._module
                                ):
                                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _extract_module_name(module_node: cst.BaseExpression) -> str:
        try:
            if isinstance(module_node, cst.Attribute):
                return (
                    AddImportTransformer._extract_module_name(module_node.value)
                    + "."
                    + module_node.attr.value
                )
            if isinstance(module_node, cst.Name):
                return module_node.value
        except Exception:
            pass
        return ""

    def leave_Module(
        self,
        original_node: cst.Module,
        updated_node: cst.Module,
    ) -> cst.Module:
        body = list(updated_node.body)

        for stmt in body:
            if self._import_matches(stmt):
                log.debug("Import déjà présent, ignoré: %s", self._module)
                return updated_node

        insert_pos = 0
        for i, stmt in enumerate(body):
            if isinstance(stmt, cst.SimpleStatementLine):
                for s in stmt.body:
                    if isinstance(s, cst.ImportFrom):
                        mod = self._extract_module_name(s.module) if s.module else ""
                        if mod == "__future__":
                            insert_pos = i + 1
                            break
                    if isinstance(s, cst.Expr) and isinstance(
                        s.value, (cst.SimpleString, cst.ConcatenatedString)
                    ):
                        insert_pos = i + 1
                        break

        new_import = self._build_import_node()
        new_body = body[:insert_pos] + [new_import] + body[insert_pos:]
        return updated_node.with_changes(body=new_body)
