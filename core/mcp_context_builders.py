# -*- coding: utf-8-sig -*-
"""
mcp_context_builders.py — REFACTO-10
Extrait de mcp_tool_handlers.py : méthodes de construction de contexte RAG/AST/Spec.

Responsabilité unique : enrichissement automatique des prompts LLM via
  - RAG mémoire (CTX-01)
  - Index AST workspace (CTX-02)
  - RAG specs similaires pour generate_spec (CTX-03)

McpContextBuilders est un mixin pur : aucun __init__, aucun lifecycle.
Suppose que self._memory, self._indexer, self._workspace sont définis par McpServer.
"""
from __future__ import annotations

import logging

log = logging.getLogger("lcca.mcp_context_builders")

# Nombre max de snippets mémoire injectés dans le system prompt
_RAG_MAX_SNIPPETS = 3
# Longueur max d'un snippet (chars) pour ne pas exploser le contexte
_RAG_SNIPPET_MAX_CHARS = 300
# Nombre max de symboles AST injectés dans le system prompt (CTX-02)
_AST_MAX_SYMBOLS = 5
# Nombre max de mots du message utilisés pour la recherche AST
_AST_QUERY_MAX_WORDS = 8
# Nombre max de specs similaires injectées dans le contexte generate_spec (CTX-03)
_SPEC_RAG_MAX = 2
# Longueur max du body_md d'une spec injectée (chars) — évite de noyer le LLM
_SPEC_RAG_BODY_MAX_CHARS = 600

# Stopwords bilingues fr/en pour la tokenisation AST (CTX-02)
_AST_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "avec", "pour", "dans", "les", "des",
    "une", "est", "que", "qui", "sur", "par", "pas", "mais",
    "comment", "peut", "quoi", "quel", "quelle",
})


class McpContextBuilders:
    """
    Mixin portant les 3 méthodes de construction de contexte enrichi.

    Attributs attendus du parent McpServer :
        self._memory, self._indexer, self._workspace
    """

    # ── CTX-02 : index AST workspace ─────────────────────────────────────────

    def _build_ast_context(self, query: str) -> str:
        """
        Sprint CTX-02 — Injection de l'index AST du workspace dans le system prompt.

        Cherche dans self._indexer.symbols_table les symboles dont le nom contient
        un mot-clé du message. Retourne un bloc compact ou "" si aucun match.
        """
        try:
            symbols_table = getattr(self._indexer, "symbols_table", {})
            if not symbols_table:
                return ""
        except Exception:
            return ""

        words = [
            w.lower() for w in query.replace("_", " ").split()
            if len(w) >= 3 and w.isalpha() and w.lower() not in _AST_STOPWORDS
        ][:_AST_QUERY_MAX_WORDS]

        if not words:
            return ""

        seen: set[str] = set()
        matches: list[str] = []

        for word in words:
            for sym_name, sym_list in symbols_table.items():
                if word not in sym_name.lower():
                    continue
                if sym_name in seen:
                    continue
                seen.add(sym_name)
                sym = sym_list[0]
                try:
                    short_path = str(sym.file).replace(str(self._workspace), "").lstrip("\\/")
                except Exception:
                    short_path = sym.file
                doc = ""
                if sym.docstring:
                    doc = " — " + sym.docstring[:80].replace("\n", " ")
                    if len(sym.docstring) > 80:
                        doc += "…"
                matches.append(f"`{sym.name}` ({sym.type}, {short_path}:{sym.line}){doc}")
                if len(matches) >= _AST_MAX_SYMBOLS:
                    break
            if len(matches) >= _AST_MAX_SYMBOLS:
                break

        if not matches:
            return ""

        joined = "\n".join(f"  • {m}" for m in matches)
        total_syms = len(symbols_table)
        total_files = len(getattr(self._indexer, "files", {}))
        return (
            "\n\n---\n"
            f"Symboles du workspace ({total_files} fichiers, {total_syms} symboles indexés) :\n"
            f"{joined}\n"
            "---"
        )

    # ── CTX-03 : RAG specs pour generate_spec ────────────────────────────────

    def _build_spec_rag_context(self, intent: str, domain: str) -> str:
        """
        Sprint CTX-03 — Injection des specs similaires mémorisées dans generate_spec.

        Cherche dans lcca_specs les specs proches de l'intent + domain courant.
        Retourne un bloc Markdown prêt à être concaténé au context de generate().
        Silencieux en cas d'erreur.
        """
        try:
            results = self._memory.search(
                query=f"{domain} {intent}", wing="lcca", n=_SPEC_RAG_MAX + 2
            )
        except Exception:
            return ""

        spec_entries = results.get("specs", [])
        if not spec_entries:
            return ""

        from core.spec_entry import SpecEntry
        usable: list[str] = []

        for entry in spec_entries:
            meta = getattr(entry, "metadata", {}) or {}
            try:
                spec = SpecEntry.from_dict(meta)
            except Exception:
                continue
            if not spec.is_usable():
                continue
            body_preview = spec.body_md[:_SPEC_RAG_BODY_MAX_CHARS]
            if len(spec.body_md) > _SPEC_RAG_BODY_MAX_CHARS:
                body_preview += "\n[…tronqué]"
            usable.append(
                f"### Spec existante : {spec.title} (id={spec.spec_id}, domain={spec.domain})\n"
                f"**Abstract** : {spec.abstract[:200]}\n\n"
                f"{body_preview}"
            )
            if len(usable) >= _SPEC_RAG_MAX:
                break

        if not usable:
            return ""

        joined = "\n\n---\n\n".join(usable)
        return (
            "\n\n"
            "## Specs similaires déjà validées (ne pas dupliquer, capitaliser dessus) :\n\n"
            f"{joined}\n"
        )

    # ── CTX-01 : RAG mémoire automatique ─────────────────────────────────────

    def _build_rag_context(self, query: str) -> str:
        """
        Sprint CTX-01 — Enrichissement RAG automatique.

        Fait un memory_search sur le message courant et injecte les top
        _RAG_MAX_SNIPPETS résultats pertinents dans le system prompt.
        Silencieux en cas d'erreur.
        """
        try:
            results = self._memory.search(query=query, wing="lcca", n=_RAG_MAX_SNIPPETS)
        except Exception:
            return ""

        snippets: list[str] = []
        for collection_key in ("solutions", "specs", "context"):
            entries = results.get(collection_key, [])
            for entry in entries:
                content = getattr(entry, "content", "") or ""
                if not content:
                    continue
                snippet = content[:_RAG_SNIPPET_MAX_CHARS]
                if len(content) > _RAG_SNIPPET_MAX_CHARS:
                    snippet += "…"
                label = {
                    "solutions": "Solution mémorisée",
                    "specs":     "Spec validée",
                    "context":   "Contexte projet",
                }.get(collection_key, "Mémoire")
                snippets.append(f"[{label}] {snippet}")
                if len(snippets) >= _RAG_MAX_SNIPPETS:
                    break
            if len(snippets) >= _RAG_MAX_SNIPPETS:
                break

        if not snippets:
            return ""

        joined = "\n".join(f"  • {s}" for s in snippets)
        return (
            "\n\n---\n"
            "Contexte projet mémorisé (utilise-le si pertinent) :\n"
            f"{joined}\n"
            "---"
        )
