# -*- coding: utf-8-sig -*-
"""
mcp_tool_handlers.py — Orchestration légère REFACTO-10

REFACTO-10 : 28.9 KB → < 8 KB
Avant : classe monolithique avec 13 handlers + 3 builders RAG/AST/Spec.
Après : héritage multiple — chaque responsabilité dans son module.

Hiérarchie MRO (ordre résolution méthodes) :
    McpToolHandlers
      ├── McpContextBuilders  (CTX-01/02/03 : _build_rag/ast/spec_rag_context)
      ├── McpHandlersCore     (memory_search, memory_store, project_search,
      │                        edit_batch, sandbox_run, evaluate_quality, analyze_error)
      ├── McpHandlersSpec     (generate_spec, validate_spec)
      ├── McpHandlersLlm      (llm_chat — RAG+AST via MRO depuis McpContextBuilders)
      └── McpHandlersExtras   (educator_status, web_search, web_cache_stats)

Rétrocompatibilité : McpToolHandlers conserve exactement la même interface publique.
McpServer hérite de McpToolHandlers → aucun changement côté McpServer.

Constantes module-level réexportées pour les tests qui les importaient depuis ce fichier.
"""
from __future__ import annotations

from core.mcp_context_builders import (
    McpContextBuilders,
    _RAG_MAX_SNIPPETS,
    _RAG_SNIPPET_MAX_CHARS,
    _AST_MAX_SYMBOLS,
    _AST_QUERY_MAX_WORDS,
    _AST_STOPWORDS,
    _SPEC_RAG_MAX,
    _SPEC_RAG_BODY_MAX_CHARS,
)
from core.mcp_handlers_core     import McpHandlersCore
from core.mcp_handlers_spec     import McpHandlersSpec
from core.mcp_handlers_llm      import McpHandlersLlm
from core.mcp_handlers_extras   import McpHandlersExtras
from core.mcp_handlers_projects import McpHandlersProjects  # PROJ-04

__all__ = [
    "McpToolHandlers",
    # Constantes réexportées (rétrocompat)
    "_RAG_MAX_SNIPPETS", "_RAG_SNIPPET_MAX_CHARS",
    "_AST_MAX_SYMBOLS", "_AST_QUERY_MAX_WORDS", "_AST_STOPWORDS",
    "_SPEC_RAG_MAX", "_SPEC_RAG_BODY_MAX_CHARS",
]


class McpToolHandlers(
    McpContextBuilders,
    McpHandlersCore,
    McpHandlersSpec,
    McpHandlersLlm,
    McpHandlersExtras,
    McpHandlersProjects,   # PROJ-04
):
    """
    Mixin agrégateur des 13 handlers _tool_* du serveur MCP.

    Aucune logique propre — tous les handlers sont hérités des 5 modules
    de responsabilité unique. L'ordre des bases suit le MRO Python (C3) :
    McpContextBuilders en premier car ses méthodes _build_*_context() sont
    appelées par McpHandlersSpec et McpHandlersLlm.

    McpServer hérite de McpToolHandlers comme avant — aucun changement d'interface.
    """
