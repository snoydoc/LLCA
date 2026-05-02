# -*- coding: utf-8-sig -*-
"""
mcp_handlers_llm.py — REFACTO-10
Extrait de mcp_tool_handlers.py : handler llm_chat avec enrichissement RAG/AST.

Responsabilité unique : conversation LLM avec historique + contexte enrichi (CTX-01/02).

McpHandlersLlm est un mixin pur : aucun __init__, aucun lifecycle.
Suppose que self._memory, self._indexer, self._workspace sont définis par McpServer,
et que les méthodes _build_rag_context() / _build_ast_context() sont apportées
par McpContextBuilders (via MRO).
"""
from __future__ import annotations

import logging
from typing import Dict

log = logging.getLogger("lcca.mcp_handlers_llm")


class McpHandlersLlm:
    """
    Mixin portant le handler llm_chat.

    Attributs attendus du parent McpServer :
        self._memory, self._indexer, self._workspace
    Méthodes attendues (via McpContextBuilders dans le MRO) :
        self._build_rag_context(query) -> str
        self._build_ast_context(query) -> str
    """

    _LCCA_SYSTEM = (
        "Tu es LCCA, un assistant IA local spécialisé en développement Python et architecture logicielle. "
        "Tu PEUX et DOIS générer du code, créer des fichiers, modifier des modules, implémenter des fonctions. "
        "Tu as accès à un système de transactions ACID (edit_batch) pour écrire dans le workspace. "
        "Tu as accès à un outil de RECHERCHE WEB (web_search) pour trouver des librairies, "
        "exemples, documentation, actualités techniques et tout sujet nécessitant une source externe. "
        "Ne dis JAMAIS que tu n'as pas accès à internet — utilise l'outil web_search. "
        "Ne dis JAMAIS que tu ne peux pas modifier ou créer des fichiers. "
        "Pour toute demande de codage, génère immédiatement le code complet et fonctionnel. "
        "Indique le chemin cible entre crochets : [workspace/fichier.py] puis le bloc ```python. "
        "Réponds en français, de façon concise et actionnable. "
        "Utilise du Markdown pour les blocs de code."
    )

    def _tool_llm_chat(self, args: Dict, emit_token=None) -> Dict:
        """
        Sprint CTX-01 — Conversation avec historique + enrichissement RAG automatique.

        Avant chaque appel Ollama, un memory_search sur le message courant injecte
        les solutions/specs mémorisées pertinentes dans le system prompt.

        args attendus :
          - message : str  — message courant de l'utilisateur
          - history : list — [{"role": "user"|"assistant", "content": str}, ...]
          - system  : str  — optionnel, surcharge le system prompt de base
        """
        message = str(args.get("message", "")).strip()
        if not message:
            raise ValueError("'message' est requis et ne peut pas être vide")

        base_system = str(args.get("system", "")).strip() or self._LCCA_SYSTEM

        # Sprint CTX-01 — enrichissement RAG mémoire automatique
        rag_context = self._build_rag_context(message)
        # Sprint CTX-02 — injection index AST workspace
        ast_context = self._build_ast_context(message)
        system = base_system + rag_context + ast_context
        if rag_context or ast_context:
            log.debug(
                "llm_chat contexte enrichi — rag=%d chars ast=%d chars",
                len(rag_context), len(ast_context),
            )

        history = args.get("history", [])
        if not isinstance(history, list):
            history = []
        clean_history = [
            {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
            for m in history
            if isinstance(m, dict)
            and m.get("role") in ("user", "assistant")
            and m.get("content")
        ]
        clean_history.append({"role": "user", "content": message})

        from core.llm_generator import OllamaClient
        from config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_MAX_TOKENS

        client = OllamaClient(
            base_url   = OLLAMA_URL,
            model      = OLLAMA_MODEL,
            timeout    = OLLAMA_TIMEOUT,
            max_tokens = OLLAMA_MAX_TOKENS,
        )

        if not client.is_available():
            return {
                "response": (
                    f"Ollama n'est pas accessible sur {OLLAMA_URL}.\n"
                    f"Lance `ollama serve` puis `ollama pull {OLLAMA_MODEL}`."
                ),
                "model":     OLLAMA_MODEL,
                "available": False,
                "done":      True,
            }

        try:
            response = client.chat(system=system, history=clean_history)
            log.info(
                "llm_chat OK — model=%s turns=%d rag=%s ast=%s",
                OLLAMA_MODEL, len(clean_history),
                "oui" if rag_context else "non",
                "oui" if ast_context else "non",
            )
            return {
                "response":  response,
                "model":     OLLAMA_MODEL,
                "available": True,
                "done":      True,
            }
        except (ConnectionError, RuntimeError) as exc:
            raise ValueError(f"Ollama erreur : {exc}") from exc
