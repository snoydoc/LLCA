# -*- coding: utf-8-sig -*-
"""
test_refacto_10.py — REFACTO-10
Tests de non-régression pour le découpage de mcp_tool_handlers.py.

Vérifie :
  1. Imports rétrocompat depuis mcp_tool_handlers (constantes + classe)
  2. Héritage multiple MRO : McpToolHandlers hérite bien des 5 mixins
  3. Chaque mixin possède ses méthodes attendues
  4. McpContextBuilders : _build_rag_context, _build_ast_context, _build_spec_rag_context
  5. McpHandlersCore    : 7 handlers de base
  6. McpHandlersSpec    : generate_spec, validate_spec
  7. McpHandlersLlm     : llm_chat + _LCCA_SYSTEM
  8. McpHandlersExtras  : educator_status, web_search, web_cache_stats
  9. Intégration : McpServer toujours fonctionnel (instanciation + tools/list)
 10. Constantes module-level inchangées

Suite : 18 tests
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Imports rétrocompat ───────────────────────────────────────────────────────

from core.mcp_tool_handlers import (
    McpToolHandlers,
    _RAG_MAX_SNIPPETS,
    _RAG_SNIPPET_MAX_CHARS,
    _AST_MAX_SYMBOLS,
    _AST_QUERY_MAX_WORDS,
    _AST_STOPWORDS,
    _SPEC_RAG_MAX,
    _SPEC_RAG_BODY_MAX_CHARS,
)
from core.mcp_context_builders import McpContextBuilders
from core.mcp_handlers_core    import McpHandlersCore
from core.mcp_handlers_spec    import McpHandlersSpec
from core.mcp_handlers_llm     import McpHandlersLlm
from core.mcp_handlers_extras  import McpHandlersExtras


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_server(tmp_path: Path):
    """Crée un McpServer avec toutes les dépendances mockées."""
    from core.mcp_server import McpServer

    mock_memory  = MagicMock()
    mock_batch   = MagicMock()
    mock_sandbox = MagicMock()
    mock_eval    = MagicMock()
    mock_error   = MagicMock()
    mock_indexer = MagicMock()

    mock_memory.search.return_value = {"solutions": [], "failures": [], "context": []}
    mock_memory.store.return_value  = MagicMock(
        stored=True, collection="lcca_patches", entry_id="abc123", reason=None
    )
    mock_batch.apply.return_value  = {"success": True, "tx_id": "tx_mock123", "evaluations": []}
    mock_sandbox.run.return_value  = (True, "out\n", "", 0)
    mock_eval_result = MagicMock()
    mock_eval_result.to_dict.return_value = {"score": 75, "passed": True, "filename": "t.py", "threshold": 60}
    mock_eval.evaluate.return_value = mock_eval_result
    mock_error_report = MagicMock()
    mock_error_report.error_type   = "SyntaxError"
    mock_error_report.file         = "foo.py"
    mock_error_report.line         = 5
    mock_error_report.message      = "invalid syntax"
    mock_error_report.suggestion   = "Corriger syntaxe"
    mock_error_report.severity     = "blocking"
    mock_error_report.auto_fixable = False
    mock_error.analyze.return_value = mock_error_report
    mock_error.generate_fix_prompt.return_value = "fix prompt"
    mock_indexer.symbols_table = {}
    mock_indexer.files = {}
    mock_indexer.index_repository.return_value = {}

    return McpServer(
        memory_engine=mock_memory,
        edit_batch=mock_batch,
        sandbox_engine=mock_sandbox,
        evaluator=mock_eval,
        error_analyzer=mock_error,
        ast_indexer=mock_indexer,
        workspace=tmp_path,
    )


def _initialized_server(tmp_path: Path):
    s = _make_server(tmp_path)
    s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return s


# ── 1. Imports rétrocompat & constantes ──────────────────────────────────────

class TestRetroCompatImports:

    def test_mcp_tool_handlers_importable(self):
        assert McpToolHandlers is not None

    def test_rag_max_snippets_value(self):
        assert _RAG_MAX_SNIPPETS == 3

    def test_rag_snippet_max_chars_value(self):
        assert _RAG_SNIPPET_MAX_CHARS == 300

    def test_ast_max_symbols_value(self):
        assert _AST_MAX_SYMBOLS == 5

    def test_ast_query_max_words_value(self):
        assert _AST_QUERY_MAX_WORDS == 8

    def test_ast_stopwords_is_frozenset(self):
        assert isinstance(_AST_STOPWORDS, frozenset)
        assert "the" in _AST_STOPWORDS
        assert "pour" in _AST_STOPWORDS

    def test_spec_rag_max_value(self):
        assert _SPEC_RAG_MAX == 2

    def test_spec_rag_body_max_chars_value(self):
        assert _SPEC_RAG_BODY_MAX_CHARS == 600


# ── 2. MRO & héritage ────────────────────────────────────────────────────────

class TestMroInheritance:

    def test_mcp_tool_handlers_inherits_context_builders(self):
        assert issubclass(McpToolHandlers, McpContextBuilders)

    def test_mcp_tool_handlers_inherits_core(self):
        assert issubclass(McpToolHandlers, McpHandlersCore)

    def test_mcp_tool_handlers_inherits_spec(self):
        assert issubclass(McpToolHandlers, McpHandlersSpec)

    def test_mcp_tool_handlers_inherits_llm(self):
        assert issubclass(McpToolHandlers, McpHandlersLlm)

    def test_mcp_tool_handlers_inherits_extras(self):
        assert issubclass(McpToolHandlers, McpHandlersExtras)

    def test_context_builders_first_in_mro(self):
        mro = McpToolHandlers.__mro__
        idx_ctx  = mro.index(McpContextBuilders)
        idx_core = mro.index(McpHandlersCore)
        assert idx_ctx < idx_core, "McpContextBuilders doit précéder McpHandlersCore dans le MRO"


# ── 3. Méthodes présentes sur chaque mixin ───────────────────────────────────

class TestMixinMethods:

    def test_context_builders_has_rag(self):
        assert callable(getattr(McpContextBuilders, "_build_rag_context", None))

    def test_context_builders_has_ast(self):
        assert callable(getattr(McpContextBuilders, "_build_ast_context", None))

    def test_context_builders_has_spec_rag(self):
        assert callable(getattr(McpContextBuilders, "_build_spec_rag_context", None))

    def test_handlers_core_has_7_tools(self):
        methods = [m for m in dir(McpHandlersCore) if m.startswith("_tool_")]
        assert len(methods) == 7

    def test_handlers_spec_has_2_tools(self):
        methods = [m for m in dir(McpHandlersSpec) if m.startswith("_tool_")]
        assert len(methods) == 2

    def test_handlers_llm_has_system_prompt(self):
        assert hasattr(McpHandlersLlm, "_LCCA_SYSTEM")
        assert "LCCA" in McpHandlersLlm._LCCA_SYSTEM

    def test_handlers_extras_has_3_tools(self):
        methods = [m for m in dir(McpHandlersExtras) if m.startswith("_tool_")]
        assert len(methods) == 3


# ── 4. Intégration : McpServer toujours fonctionnel ──────────────────────────

class TestMcpServerIntegration:

    def test_server_instantiation(self, tmp_path: Path):
        server = _make_server(tmp_path)
        assert server is not None

    def test_tools_list_still_13(self, tmp_path: Path):
        server   = _initialized_server(tmp_path)
        response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools    = response["result"]["tools"]
        assert len(tools) == 13

    def test_memory_search_still_works(self, tmp_path: Path):
        server   = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "memory_search", "arguments": {"query": "test"}},
        })
        assert "result" in response

    def test_mcp_tool_handlers_is_in_server_mro(self, tmp_path: Path):
        from core.mcp_server import McpServer
        assert issubclass(McpServer, McpToolHandlers)
