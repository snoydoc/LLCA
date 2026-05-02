# -*- coding: utf-8-sig -*-
"""
llm_code_utils.py — REFACTO-11
Extrait de llm_generator.py : extraction et validation du code généré.

Responsabilité unique :
  - CodeExtractor  : extrait le Python brut depuis la réponse LLM (fences, heuristique)
  - FallbackGenerator : génère un stub minimal si Ollama est indisponible ou produit du code invalide
"""
from __future__ import annotations

import re


class CodeExtractor:
    _FENCE_RE = re.compile(r"```(?:python)?\s*\n?(.*?)\n?```", re.DOTALL)

    def extract(self, raw: str) -> str:
        raw     = raw.strip()
        matches = self._FENCE_RE.findall(raw)
        if matches:
            return max(matches, key=len).strip()
        lines, code_lines, in_code = raw.splitlines(), [], False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_code:
                    code_lines.append(line)
                continue
            if stripped.startswith((
                "def ", "class ", "import ", "from ", "#", "@",
                "return ", "raise ", "pass", "async ",
            )):
                in_code = True
            if in_code:
                code_lines.append(line)
        return "\n".join(code_lines).strip() if code_lines else raw

    def is_valid_python(self, code: str) -> bool:
        try:
            compile(code, "<generated>", "exec")
            return True
        except SyntaxError:
            return False

    def sanitize(self, code: str) -> str:
        code = re.sub(r"```\w*", "", code)
        return code.replace("\r\n", "\n").replace("\r", "\n").strip()


class FallbackGenerator:
    def generate(self, op, intent) -> str:
        symbol  = getattr(op, "target_symbol", None) or "new_function"
        details = getattr(intent, "details", "") or ""
        action  = getattr(op, "action", "create")
        patch   = getattr(op, "patch_type", "add_function")
        target  = getattr(intent, "target", "") or ""

        if action == "create":
            return (
                f"# -*- coding: utf-8-sig -*-\n"
                f'"""\n{target} — LCCA V5 Fusion\nGenere automatiquement (stub).\n"""\n\n'
                f"from __future__ import annotations\n\n\ndef {symbol}():\n"
                f'    """TODO: Implementer {details}."""\n'
                f"    raise NotImplementedError('{symbol}')\n"
            )
        if patch == "add_function":
            return (
                f"def {symbol}():\n"
                f'    """TODO: Implementer {details}."""\n'
                f"    raise NotImplementedError('{symbol}')\n"
            )
        if patch == "modify_function":
            return (
                f'    """TODO: Modifier {details}."""\n'
                f"    raise NotImplementedError('{symbol} — a modifier')\n"
            )
        if patch == "add_import":
            module = symbol or (details.split(".")[0] if details else "module")
            return f"import {module}"
        return f"# TODO: {details}\n"
