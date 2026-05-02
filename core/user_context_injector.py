# -*- coding: utf-8-sig -*-
"""
user_context_injector.py - LCCA V10 / Mode Projets
Sprint PROJ-07 - Worker : generation bloc prompt UserContext

Genere un bloc compact (≤ 800 tokens) insere apres le contexte projet
dans le prompt systeme. Injecte aussi user_prefix dans ProjectContext.

Invariants :
  - Jamais plus de 800 tokens injectes (≈ 3200 chars, approximation 4 chars/token)
  - Couche communication uniquement : pas de code, pas de chemins absolus
  - FIFO sur 'learned' si depassement du budget
  - Bloc vide ("") si aucune donnee utile
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.user_context import UserContextState

log = logging.getLogger(__name__)

# Budget token max injecte (invariant spec §4.3)
MAX_INJECT_TOKENS = 800
# Approximation 1 token ~ 4 chars (conforme aux autres modules LCCA)
CHARS_PER_TOKEN = 4
MAX_INJECT_CHARS = MAX_INJECT_TOKENS * CHARS_PER_TOKEN  # 3200


class UserContextInjector:
    """
    Worker PROJ-07 : genere le bloc prompt UserContext.

    Usage :
        injector = UserContextInjector()
        prefix   = injector.build(state)
        # prefix est une str prete a etre inseree dans le prompt systeme
    """

    def build(self, state: Optional["UserContextState"]) -> str:
        """
        Genere le bloc [USER CONTEXT] depuis un UserContextState.

        Si state est None ou vide → retourne "".
        Respecte le budget MAX_INJECT_CHARS (FIFO sur learned si besoin).
        """
        if state is None:
            return ""

        lines = self._collect_lines(state)
        if not lines:
            return ""

        block = self._assemble_block(lines)
        return block

    # ---- Construction des lignes ----------------------------------------

    def _collect_lines(self, state: "UserContextState") -> list[str]:
        """Collecte les lignes d'information, ordre de priorite."""
        lines: list[str] = []
        data = state.data

        # 1. Identite
        identity = data.get("identity", {})
        parts = []
        if identity.get("name"):
            parts.append(f"Prénom : {identity['name']}")
        if identity.get("locale"):
            parts.append(f"Locale : {identity['locale']}")
        if parts:
            lines.append("- " + " | ".join(parts))

        # 2. Communication
        comm = data.get("communication", {})
        comm_parts = []
        if comm.get("tone"):
            comm_parts.append(f"Ton : {comm['tone']}")
        if comm.get("verbosity"):
            comm_parts.append(f"Verbosité : {comm['verbosity']}")
        if comm.get("language"):
            comm_parts.append(f"Langue : {comm['language']}")
        emoji_val = comm.get("prefers_emoji")
        if emoji_val is not None:
            comm_parts.append(f"Emoji : {'oui' if emoji_val else 'non'}")
        if comm_parts:
            lines.append("- " + " | ".join(comm_parts))

        # 3. Raccourcis / aliases
        shortcuts = data.get("shortcuts", {})
        aliases = shortcuts.get("aliases", {})
        if aliases:
            alias_str = ", ".join(
                f'"{k}" = {v}' for k, v in list(aliases.items())[:5]
            )
            lines.append(f"- Raccourcis : {alias_str}")

        fav_cmds = shortcuts.get("favorite_commands", [])
        if fav_cmds:
            cmds_str = ", ".join(str(c) for c in fav_cmds[:5])
            lines.append(f"- Commandes favorites : {cmds_str}")

        # 4. Style appris (FIFO tronque si budget depasse)
        learned = data.get("learned", {})
        style_items = learned.get("coding_style", [])
        pain_items  = learned.get("pain_points", [])
        pref_size   = learned.get("preferred_file_size", "")

        learned_lines = []
        if style_items:
            style_str = ", ".join(str(s) for s in style_items[:6])
            learned_lines.append(f"- Style connu : {style_str}")
        if pain_items:
            pain_str = ", ".join(str(p) for p in pain_items[:4])
            learned_lines.append(f"- Points de friction : {pain_str}")
        if pref_size:
            learned_lines.append(f"- Taille modules préférée : {pref_size}")

        # 5. Workflow
        workflow = data.get("workflow", {})
        model_override = workflow.get("preferred_model")
        if model_override:
            lines.append(f"- Modèle préféré : {model_override}")

        # Assembler sans les lignes learned d'abord
        base_block = self._format_block(lines)
        base_chars = len(base_block)

        # Ajouter learned FIFO dans le budget restant
        budget_left = MAX_INJECT_CHARS - base_chars - len("\n[/USER CONTEXT]\n")
        for ll in learned_lines:
            if budget_left >= len(ll) + 1:
                lines.append(ll)
                budget_left -= len(ll) + 1
            # FIFO : on arrete si plus de budget

        return lines

    # ---- Assemblage bloc ------------------------------------------------

    def _format_block(self, lines: list[str]) -> str:
        """Formate le bloc sans les delimiteurs."""
        return "\n".join(lines)

    def _assemble_block(self, lines: list[str]) -> str:
        """Assemble le bloc final avec delimiteurs."""
        inner = "\n".join(lines)
        block = f"[USER CONTEXT — {MAX_INJECT_TOKENS} tokens max]\n{inner}\n[/USER CONTEXT]"
        # Guard final : si le bloc depasse quand meme (cas extreme)
        if len(block) > MAX_INJECT_CHARS + 100:
            # Tronquer inner brutalement
            max_inner = MAX_INJECT_CHARS - 60
            inner = inner[:max_inner] + "…"
            block = f"[USER CONTEXT — {MAX_INJECT_TOKENS} tokens max]\n{inner}\n[/USER CONTEXT]"
        return block

    # ---- Integration ProjectContext ------------------------------------

    def inject_into_context(self, context: object, state: Optional["UserContextState"]) -> None:
        """
        Peuple context.user_prefix avec le bloc genere.

        Compatible avec ProjectContext (PROJ-03) qui expose user_prefix = "".
        """
        prefix = self.build(state)
        try:
            context.user_prefix = prefix  # type: ignore[union-attr]
        except AttributeError:
            log.warning(
                "UserContextInjector.inject_into_context : "
                "l'objet context n'a pas d'attribut user_prefix"
            )
