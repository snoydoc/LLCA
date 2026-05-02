# -*- coding: utf-8-sig -*-
"""
context_assembler.py — LCCA V5 Fusion
Sprint 05 — TASK-05-05

Gestion de la fenêtre de contexte LLM.
Assemble identity + intent + fichiers + souvenirs MemPalace
en respectant MAX_CONTEXT_TOKENS (défaut 8000).

Usage :
    assembler = ContextAssembler(palace)
    prompt = assembler.assemble(intent, ["auth.py"], {"auth.py": "..."})
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("lcca.context_assembler")

try:
    from config import MAX_CONTEXT_TOKENS
except ImportError:  # pragma: no cover
    MAX_CONTEXT_TOKENS = 8_000


class ContextAssembler:
    """
    Assemble le prompt contexte LLM dans le budget tokens.

    Ordre de priorité (jamais tronqué → optionnel) :
        1. Identity Layer 0        — critique
        2. Intent + fichiers cibles — critique
        3. Contenu des fichiers     — tronqué si besoin
        4. Souvenirs MemPalace      — optionnels, derniers ajoutés

    Attributes:
        palace    : Instance MemPalaceClient.
        max_tokens: Budget tokens maximum.
    """

    def __init__(self, palace, max_tokens: int = MAX_CONTEXT_TOKENS) -> None:
        self.palace = palace
        self.max_tokens = max_tokens

    # ── Interface publique ────────────────────────────────────────────────────

    def assemble(
        self,
        intent,
        target_files: List[str],
        file_contents: Dict[str, str],
        wing: Optional[str] = None,
        room: Optional[str] = None,
    ) -> str:
        """
        Assemble le prompt contexte.

        Args:
            intent        : Intent (DSLParser) avec project/target/action/details.
            target_files  : Liste des fichiers ciblés.
            file_contents : Dict {path: contenu}.
            wing/room     : Filtres MemPalace pour les souvenirs pertinents.

        Returns:
            str : Prompt assemblé respectant max_tokens.
        """
        # Section 1 : Identity (priorité maximale)
        ctx = self.palace.wake_up(wing=wing, room=room)
        identity_text = ctx.get("identity", "")

        # Section 2 : Intent + fichiers cibles
        intent_text = self._format_intent(intent, target_files)

        # Calcul budget restant après sections critiques
        critical_tokens = (
            self.estimate_tokens(identity_text)
            + self.estimate_tokens(intent_text)
        )
        remaining = self.max_tokens - critical_tokens

        # Section 3 : Contenu des fichiers (tronqué si besoin)
        files_text = self._format_files(file_contents, budget=max(0, remaining - 500))

        # Section 4 : Souvenirs pertinents (optionnels)
        memories_text = ""
        mem_budget = remaining - self.estimate_tokens(files_text)
        if mem_budget > 200:
            query = f"{getattr(intent, 'action', '')} {getattr(intent, 'details', '')}"
            memories_text = self._format_memories(query, wing=wing, budget=mem_budget)

        # Assemblage final
        sections = [
            "# LCCA V5 — Context",
            "\n## Identity",
            identity_text,
            "\n## Task",
            intent_text,
        ]
        if files_text:
            sections += ["\n## Files to modify", files_text]
        if memories_text:
            sections += ["\n## Relevant memories", memories_text]

        result = "\n".join(sections)

        # Vérification finale
        total = self.estimate_tokens(result)
        if total > self.max_tokens:
            log.warning(
                "ContextAssembler: dépassement budget %d/%d tokens — troncature finale.",
                total, self.max_tokens,
            )
            result = self._hard_truncate(result)

        return result

    # ── Formatage sections ────────────────────────────────────────────────────

    def _format_intent(self, intent, target_files: List[str]) -> str:
        """Formate la section Task."""
        lines = []
        if hasattr(intent, "project") and intent.project:
            lines.append(f"Project: {intent.project}")
        if hasattr(intent, "target") and intent.target:
            sub = getattr(intent, "sub_target", None)
            lines.append(f"Target: {intent.target}" + (f" / {sub}" if sub else ""))
        if hasattr(intent, "action") and intent.action:
            details = getattr(intent, "details", "") or ""
            lines.append(f"Action: {intent.action} {details}".rstrip())
        if target_files:
            lines.append(f"Files: {', '.join(target_files)}")
        return "\n".join(lines)

    def _format_files(self, file_contents: Dict[str, str], budget: int) -> str:
        """Formate le contenu des fichiers en respectant le budget tokens."""
        if not file_contents:
            return ""

        parts = []
        tokens_used = 0
        tokens_per_file = max(100, budget // max(1, len(file_contents)))

        for path, content in file_contents.items():
            header = f"### {path}\n```python\n"
            footer = "\n```"
            available = tokens_per_file - self.estimate_tokens(header + footer)
            if available <= 0:
                continue

            truncated = self._truncate_lines(content, available)

            if truncated != content:
                truncation_pct = (1 - len(truncated) / max(1, len(content))) * 100
                if truncation_pct > 20:
                    log.warning(
                        "Fichier %s tronqué à %.0f%% (budget tokens).", path, 100 - truncation_pct
                    )
                truncated += "\n# ... [tronqué]"

            section = header + truncated + footer
            tokens_used += self.estimate_tokens(section)
            if tokens_used > budget:
                break
            parts.append(section)

        return "\n\n".join(parts)

    def _format_memories(self, query: str, wing: Optional[str], budget: int) -> str:
        """Formate les souvenirs MemPalace pertinents."""
        if not query.strip():
            return ""
        try:
            memories = self.palace.search_memories(query, wing=wing, n_results=5)
        except Exception as exc:
            log.debug("_format_memories error: %s", exc)
            return ""

        if not memories:
            return ""

        lines = []
        tokens_used = 0
        for mem in memories:
            line = f"- {mem.content[:200]}"
            t = self.estimate_tokens(line)
            if tokens_used + t > budget:
                break
            lines.append(line)
            tokens_used += t

        return "\n".join(lines)

    # ── Utilitaires tokens ────────────────────────────────────────────────────

    def estimate_tokens(self, text: str) -> int:
        """Estimation rapide : ~4 chars = 1 token."""
        return max(0, len(str(text) if text is not None else "") // 4)

    def _truncate_lines(self, text: str, token_budget: int) -> str:
        """Tronque proprement à la fin d'une ligne (pas au milieu)."""
        char_budget = token_budget * 4
        if len(text) <= char_budget:
            return text
        truncated = text[:char_budget]
        # Couper à la dernière ligne complète
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        return truncated

    def _hard_truncate(self, text: str) -> str:
        """Troncature brutale si le budget est dépassé malgré tout."""
        char_budget = self.max_tokens * 4
        if len(text) <= char_budget:
            return text
        return text[:char_budget].rsplit("\n", 1)[0] + "\n# ... [contexte tronqué]"

    def truncate_to_fit(
        self, sections: List[Tuple[str, int]], budget: int
    ) -> str:
        """
        Assemble des sections (contenu, priorité) dans le budget.
        Priorité haute (grande valeur) = jamais tronqué.
        Priorité basse = tronqué ou omis si plus de place.
        """
        # Séparer critiques (priorité ≥ 10) et optionnelles
        critical = [(c, p) for c, p in sections if p >= 10]
        optional = [(c, p) for c, p in sections if p < 10]
        optional.sort(key=lambda x: x[1], reverse=True)

        result_parts = []
        tokens_used = 0

        for content, _ in critical:
            result_parts.append(content)
            tokens_used += self.estimate_tokens(content)

        for content, _ in optional:
            t = self.estimate_tokens(content)
            if tokens_used + t <= budget:
                result_parts.append(content)
                tokens_used += t

        return "\n".join(result_parts)
