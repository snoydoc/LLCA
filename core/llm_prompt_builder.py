# -*- coding: utf-8-sig -*-
"""
llm_prompt_builder.py — REFACTO-11
Extrait de llm_generator.py : construction des prompts LLM.

Responsabilité unique : PromptBuilder — construit les prompts système/utilisateur
selon le type d'opération (create, add_function, modify_function, add_import).
"""
from __future__ import annotations


class PromptBuilder:
    _SYSTEM = (
        "You are LCCA, an expert Python code generator. "
        "Generate ONLY valid Python code. No explanations, no markdown fences, "
        "no comments except inline docstrings. "
        "Follow PEP 8. Use type hints. Raise NotImplementedError if logic is unknown."
    )

    def build(
        self,
        op,
        intent,
        context: str = "",
        skill_context: str = "",
    ) -> tuple[str, str]:
        action     = getattr(op, "action",        "create")
        patch_type = getattr(op, "patch_type",    "add_function")
        symbol     = getattr(op, "target_symbol", None) or "new_function"
        details    = getattr(intent, "details",   "") or ""
        project    = getattr(intent, "project",   "") or "LCCA"
        target     = getattr(intent, "target",    "") or ""

        if action == "create":
            user = self._prompt_create(op.file, project, target, details)
        elif patch_type == "modify_function":
            user = self._prompt_modify(symbol, details, context)
        elif patch_type == "add_import":
            user = self._prompt_import(symbol, details)
        else:
            user = self._prompt_add_function(symbol, details, context)

        # V9-02-A : injection few-shot en tête du user prompt
        if skill_context:
            user = (
                "## Exemples de code LCCA existants (style a imiter)\n\n"
                + skill_context
                + "\n\n## Votre tache\n\n"
                + user
            )

        return self._SYSTEM, user

    def _prompt_create(self, file: str, project: str, target: str, details: str) -> str:
        return (
            f"Create a new Python module for project '{project}'.\n"
            f"File: {file}\nModule purpose: {target} — {details}\n\n"
            f"Requirements:\n- UTF-8 BOM header\n- Module docstring\n"
            f"- from __future__ import annotations\n- No external imports\n\n"
            f"Generate the complete module content:"
        )

    def _prompt_add_function(self, symbol: str, details: str, context: str) -> str:
        ctx = f"\n\nExisting file:\n```python\n{context[:1500]}\n```" if context else ""
        return (
            f"Add a Python function named '{symbol}'.\nPurpose: {details}\n"
            f"Requirements: type hints, docstring, stub body{ctx}\n\n"
            f"Generate ONLY the function definition:"
        )

    def _prompt_modify(self, symbol: str, details: str, context: str) -> str:
        ctx = f"\n\nCurrent function:\n```python\n{context[:800]}\n```" if context else ""
        return (
            f"Modify '{symbol}'.\nChange: {details}\n"
            f"Keep signature, replace body{ctx}\n\n"
            f"Generate ONLY the new function body:"
        )

    def _prompt_import(self, module: str, details: str) -> str:
        return (
            f"Generate a Python import statement.\n"
            f"Module: {module}\nContext: {details}\n"
            f"Generate ONLY the import line:"
        )
