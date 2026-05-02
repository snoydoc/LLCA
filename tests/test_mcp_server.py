# -*- coding: utf-8-sig -*-
"""
test_mcp_server.py — LCCA V7
Sprint 12 — TASK-12-10

Tests unitaires pour McpServer (JSON-RPC 2.0 stdio, lifecycle MCP, 7 tools).

Stratégie :
  - Toutes les dépendances injectées via MagicMock
  - Tests lifecycle MCP (initialize, notifications/initialized, tools/list, tools/call)
  - Tests de chaque tool handler (7 tools)
  - Tests sécurité (path traversal, absolu, tool inconnu)
  - Tests audit + telemetry (silencieux)
  - Tests boucle stdio (JSON invalide, notification sans réponse)

Suite : 40 tests
"""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from core.mcp_server import McpServer, _ERR_INVALID_PARAMS, _ERR_METHOD_NOT_FOUND, _ERR_SECURITY


# ──────────────────────────────────────────────────────────────────────────────
# Helpers & fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _make_server(tmp_path: Path) -> McpServer:
    """
    Crée un McpServer avec toutes les dépendances mockées.
    """
    mock_memory  = MagicMock()
    mock_batch   = MagicMock()
    mock_sandbox = MagicMock()
    mock_eval    = MagicMock()
    mock_error   = MagicMock()
    mock_indexer = MagicMock()

    # Defaults mock returns
    mock_memory.search.return_value = {"solutions": [], "failures": [], "context": []}
    mock_memory.store.return_value  = MagicMock(
        stored=True, collection="lcca_patches", entry_id="abc123", reason=None
    )

    mock_batch.apply.return_value = {
        "success": True, "tx_id": "tx_mock123", "evaluations": [{"score": 80, "passed": True}]
    }

    mock_sandbox.run.return_value = (True, "output\n", "", 0)

    mock_eval_result = MagicMock()
    mock_eval_result.to_dict.return_value = {
        "score": 75, "passed": True, "filename": "test.py", "threshold": 60
    }
    mock_eval.evaluate.return_value = mock_eval_result

    mock_error_report = MagicMock()
    mock_error_report.error_type   = "SyntaxError"
    mock_error_report.file         = "foo.py"
    mock_error_report.line         = 5
    mock_error_report.message      = "invalid syntax"
    mock_error_report.suggestion   = "Corriger la syntaxe ligne 5"
    mock_error_report.severity     = "blocking"
    mock_error_report.auto_fixable = False
    mock_error.analyze.return_value = mock_error_report
    mock_error.generate_fix_prompt.return_value = "Prompt: corriger syntaxe"

    mock_indexer.symbols_table = {}
    mock_indexer.files = {}
    mock_indexer.index_repository.return_value = {}

    server = McpServer(
        memory_engine=mock_memory,
        edit_batch=mock_batch,
        sandbox_engine=mock_sandbox,
        evaluator=mock_eval,
        error_analyzer=mock_error,
        ast_indexer=mock_indexer,
        workspace=tmp_path,
    )
    return server


def _initialized_server(tmp_path: Path) -> McpServer:
    """Crée un McpServer déjà initialisé (après handshake)."""
    server = _make_server(tmp_path)
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return server


# ──────────────────────────────────────────────────────────────────────────────
# 1. Constructeur
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpServerConstructor:

    def test_instantiation_with_mocks(self, tmp_path: Path) -> None:
        """McpServer s'instancie sans erreur avec des mocks."""
        server = _make_server(tmp_path)
        assert server is not None
        assert server._initialized is False

    def test_workspace_set(self, tmp_path: Path) -> None:
        """Le workspace est correctement assigné."""
        server = _make_server(tmp_path)
        assert server._workspace == tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# 2. Lifecycle MCP
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpLifecycle:

    def test_initialize_returns_protocol_version(self, tmp_path: Path) -> None:
        """La réponse initialize doit contenir protocolVersion."""
        server   = _make_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"}
        })
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "protocolVersion" in response["result"]
        assert response["result"]["serverInfo"]["name"] == "lcca-v7-mcp"

    def test_initialize_returns_capabilities(self, tmp_path: Path) -> None:
        """La réponse initialize doit inclure les capabilities."""
        server   = _make_server(tmp_path)
        response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        caps = response["result"]["capabilities"]
        assert "tools" in caps
        assert "resources" in caps

    def test_initialized_notification_no_response(self, tmp_path: Path) -> None:
        """notifications/initialized doit retourner None (pas de réponse)."""
        server = _make_server(tmp_path)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        resp = server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert resp is None
        assert server._initialized is True

    def test_tools_list_returns_7_tools(self, tmp_path: Path) -> None:
        """tools/list doit retourner exactement 24 tools."""
        server = _initialized_server(tmp_path)
        response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = response["result"]["tools"]
        assert len(tools) == 24

    def test_tools_list_names(self, tmp_path: Path) -> None:
        """Les 24 noms de tools doivent correspondre a la spec actuelle."""
        server = _initialized_server(tmp_path)
        response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in response["result"]["tools"]}
        expected = {
            "memory_search", "memory_store", "project_search",
            "edit_batch", "sandbox_run", "evaluate_quality", "analyze_error",
            "generate_spec", "validate_spec",
            "llm_chat", "web_search", "web_cache_stats",
            "educator_status",  # ED-03
            # Mode Projets — PROJ-04
            "project_list", "project_create", "project_open", "project_close",
            "project_archive", "project_switch", "project_get_context",
            "project_save_context", "project_healthcheck", "project_compact_history",
            # PROJ-UI-02
            "inspiration_generate",
        }
        assert names == expected

    def test_tools_call_requires_initialized(self, tmp_path: Path) -> None:
        """tools/call avant initialize doit retourner une erreur."""
        server = _make_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 3,
            "method": "tools/call",
            "params": {"name": "sandbox_run", "arguments": {"code": "x=1"}}
        })
        assert "error" in response

    def test_unknown_method_returns_error(self, tmp_path: Path) -> None:
        """Une méthode inconnue doit retourner une erreur JSON-RPC."""
        server = _make_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 99, "method": "nonexistent/method", "params": {}
        })
        assert "error" in response
        assert response["error"]["code"] == _ERR_METHOD_NOT_FOUND

    def test_ping_response(self, tmp_path: Path) -> None:
        """La méthode ping doit retourner pong."""
        server = _make_server(tmp_path)
        response = server.handle({"jsonrpc": "2.0", "id": 5, "method": "ping"})
        assert response["result"]["pong"] is True

    def test_unknown_notification_silent(self, tmp_path: Path) -> None:
        """Une notification inconnue (sans id) doit être silencieuse (None)."""
        server = _make_server(tmp_path)
        resp = server.handle({"jsonrpc": "2.0", "method": "some/notification"})
        assert resp is None


# ──────────────────────────────────────────────────────────────────────────────
# 3. Tool : memory_search
# ──────────────────────────────────────────────────────────────────────────────

class TestToolMemorySearch:

    def test_memory_search_calls_engine(self, tmp_path: Path) -> None:
        """memory_search appelle MemoryEngine.search() avec les bons args."""
        server = _initialized_server(tmp_path)
        server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "memory_search", "arguments": {"query": "SyntaxError fix", "n": 3}}
        })
        server._memory.search.assert_called_once_with(query="SyntaxError fix", wing="lcca", n=3)

    def test_memory_search_empty_query_error(self, tmp_path: Path) -> None:
        """Un query vide doit retourner une erreur params."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "memory_search", "arguments": {"query": ""}}
        })
        assert "error" in response
        assert response["error"]["code"] == _ERR_INVALID_PARAMS

    def test_memory_search_returns_collections(self, tmp_path: Path) -> None:
        """La réponse doit contenir solutions, failures, context."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "memory_search", "arguments": {"query": "auth"}}
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert "solutions" in content
        assert "failures" in content
        assert "context" in content


# ──────────────────────────────────────────────────────────────────────────────
# 4. Tool : memory_store
# ──────────────────────────────────────────────────────────────────────────────

class TestToolMemoryStore:

    def test_memory_store_calls_engine(self, tmp_path: Path) -> None:
        """memory_store appelle MemoryEngine.store() avec les bons args."""
        server = _initialized_server(tmp_path)
        server.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {
                "name": "memory_store",
                "arguments": {"collection": "lcca_patches", "payload": {"tx_id": "tx_abc"}}
            }
        })
        server._memory.store.assert_called_once_with(
            collection="lcca_patches", payload={"tx_id": "tx_abc"}
        )

    def test_memory_store_missing_collection_error(self, tmp_path: Path) -> None:
        """memory_store sans collection doit retourner une erreur."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "memory_store", "arguments": {"payload": {}}}
        })
        assert "error" in response

    def test_memory_store_non_dict_payload_error(self, tmp_path: Path) -> None:
        """Un payload non-dict doit lever TypeError → erreur params."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {
                "name": "memory_store",
                "arguments": {"collection": "lcca_failures", "payload": "not a dict"}
            }
        })
        assert "error" in response
        assert response["error"]["code"] == _ERR_INVALID_PARAMS


# ──────────────────────────────────────────────────────────────────────────────
# 5. Tool : project_search
# ──────────────────────────────────────────────────────────────────────────────

class TestToolProjectSearch:

    def test_project_search_returns_symbols_and_files(self, tmp_path: Path) -> None:
        """project_search retourne symbols et files."""
        server = _initialized_server(tmp_path)
        server._indexer.symbols_table = {}
        server._indexer.files = {"auth.py": MagicMock()}
        response = server.handle({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "project_search", "arguments": {"query": "auth"}}
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert "symbols" in content
        assert "files" in content

    def test_project_search_empty_query_error(self, tmp_path: Path) -> None:
        """query vide → erreur params."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "project_search", "arguments": {"query": ""}}
        })
        assert "error" in response

    def test_project_search_path_traversal_error(self, tmp_path: Path) -> None:
        """file_path avec traversal → erreur sécurité."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {
                "name": "project_search",
                "arguments": {"query": "auth", "file_path": "../../../etc/passwd"}
            }
        })
        assert "error" in response
        assert response["error"]["code"] == _ERR_SECURITY


# ──────────────────────────────────────────────────────────────────────────────
# 6. Tool : edit_batch
# ──────────────────────────────────────────────────────────────────────────────

class TestToolEditBatch:

    def test_edit_batch_calls_apply(self, tmp_path: Path) -> None:
        """edit_batch appelle McpEditBatch.apply() avec les bons args."""
        server = _initialized_server(tmp_path)
        files = [{"path": "mod.py", "patch_type": "add_function", "code": "def f(): pass"}]
        server.handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "edit_batch", "arguments": {"files": files}}
        })
        server._edit_batch.apply.assert_called_once_with(files)

    def test_edit_batch_empty_files_error(self, tmp_path: Path) -> None:
        """Une liste vide doit retourner une erreur params."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "edit_batch", "arguments": {"files": []}}
        })
        assert "error" in response

    def test_edit_batch_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Path traversal dans les fichiers → erreur sécurité avant apply()."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {
                "name": "edit_batch",
                "arguments": {
                    "files": [{"path": "../../../etc/passwd", "patch_type": "add_function", "code": "x=1"}]
                }
            }
        })
        assert "error" in response
        assert response["error"]["code"] == _ERR_SECURITY
        # apply() ne doit PAS avoir été appelé
        server._edit_batch.apply.assert_not_called()

    def test_edit_batch_success_reindexes(self, tmp_path: Path) -> None:
        """Après un edit_batch réussi, l'indexer est re-indexé."""
        server = _initialized_server(tmp_path)
        files = [{"path": "mod.py", "patch_type": "add_function", "code": "def f(): pass"}]
        server.handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "edit_batch", "arguments": {"files": files}}
        })
        server._indexer.index_repository.assert_called()

    def test_edit_batch_failure_no_reindex(self, tmp_path: Path) -> None:
        """Après un edit_batch échoué, l'indexer n'est PAS re-indexé."""
        server = _initialized_server(tmp_path)
        server._edit_batch.apply.return_value = {"success": False, "error": "bad", "rolled_back": True}
        # reset call count (constructor called it once)
        server._indexer.index_repository.reset_mock()
        files = [{"path": "mod.py", "patch_type": "add_function", "code": "def f(): pass"}]
        server.handle({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "edit_batch", "arguments": {"files": files}}
        })
        server._indexer.index_repository.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# 7. Tool : sandbox_run
# ──────────────────────────────────────────────────────────────────────────────

class TestToolSandboxRun:

    def test_sandbox_run_returns_stdout(self, tmp_path: Path) -> None:
        """sandbox_run retourne success, stdout, stderr, exit_code."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "sandbox_run", "arguments": {"code": "print('hi')"}}
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert "success" in content
        assert "stdout" in content

    def test_sandbox_run_empty_code_error(self, tmp_path: Path) -> None:
        """Code vide → erreur params."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "sandbox_run", "arguments": {"code": ""}}
        })
        assert "error" in response

    def test_sandbox_run_timeout_zero_error(self, tmp_path: Path) -> None:
        """timeout <= 0 → erreur params."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "sandbox_run", "arguments": {"code": "x=1", "timeout": 0}}
        })
        assert "error" in response


# ──────────────────────────────────────────────────────────────────────────────
# 8. Tool : evaluate_quality
# ──────────────────────────────────────────────────────────────────────────────

class TestToolEvaluateQuality:

    def test_evaluate_quality_calls_evaluator(self, tmp_path: Path) -> None:
        """evaluate_quality appelle CodeEvaluator.evaluate() avec les bons args."""
        server = _initialized_server(tmp_path)
        server.handle({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {
                "name": "evaluate_quality",
                "arguments": {"code": "def f(): pass", "filename": "test.py"}
            }
        })
        server._evaluator.evaluate.assert_called_once_with(
            code="def f(): pass", filename="test.py"
        )

    def test_evaluate_quality_returns_score(self, tmp_path: Path) -> None:
        """La réponse doit contenir score et passed."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "evaluate_quality", "arguments": {"code": "x = 1"}}
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert "score" in content
        assert "passed" in content

    def test_evaluate_quality_empty_code_error(self, tmp_path: Path) -> None:
        """Code vide → erreur params."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "evaluate_quality", "arguments": {"code": ""}}
        })
        assert "error" in response


# ──────────────────────────────────────────────────────────────────────────────
# 9. Tool : analyze_error
# ──────────────────────────────────────────────────────────────────────────────

class TestToolAnalyzeError:

    def test_analyze_error_calls_analyzer(self, tmp_path: Path) -> None:
        """analyze_error appelle ErrorAnalyzer.analyze()."""
        server = _initialized_server(tmp_path)
        server.handle({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {
                "name": "analyze_error",
                "arguments": {
                    "error_type": "SyntaxError",
                    "error_message": "invalid syntax",
                    "file_path": "foo.py",
                }
            }
        })
        server._error_analyzer.analyze.assert_called_once()

    def test_analyze_error_returns_suggestion(self, tmp_path: Path) -> None:
        """La réponse doit contenir suggestion et fix_prompt."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {
                "name": "analyze_error",
                "arguments": {
                    "error_type": "ImportError",
                    "error_message": "No module named 'requests'",
                    "file_path": "app.py",
                }
            }
        })
        content = json.loads(response["result"]["content"][0]["text"])
        assert "suggestion" in content
        assert "fix_prompt" in content
        assert "severity" in content


# ──────────────────────────────────────────────────────────────────────────────
# 10. Sécurité — tool inconnu
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpSecurity:

    def test_unknown_tool_returns_error(self, tmp_path: Path) -> None:
        """Un tool inconnu doit retourner une erreur METHOD_NOT_FOUND."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 99, "method": "tools/call",
            "params": {"name": "evil_tool", "arguments": {}}
        })
        assert "error" in response
        assert response["error"]["code"] == _ERR_METHOD_NOT_FOUND

    def test_edit_batch_absolute_path_blocked(self, tmp_path: Path) -> None:
        """Chemin absolu dans edit_batch → erreur sécurité."""
        server = _initialized_server(tmp_path)
        response = server.handle({
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {
                "name": "edit_batch",
                "arguments": {
                    "files": [{"path": "/etc/passwd", "action": "create", "code": "x=1"}]
                }
            }
        })
        assert "error" in response
        assert response["error"]["code"] == _ERR_SECURITY


# ──────────────────────────────────────────────────────────────────────────────
# 11. Boucle stdio
# ──────────────────────────────────────────────────────────────────────────────

class TestStdioLoop:

    def test_invalid_json_returns_parse_error(self, tmp_path: Path, capsys) -> None:
        """Une ligne JSON invalide doit déclencher une erreur -32700."""
        server = _make_server(tmp_path)
        fake_stdin = StringIO("not valid json\n")
        with patch("sys.stdin", fake_stdin), patch("builtins.print") as mock_print:
            server.serve_stdio()
        # Vérifie qu'un message d'erreur -32700 a été écrit
        printed_args = [call[0][0] for call in mock_print.call_args_list]
        error_responses = [
            json.loads(s) for s in printed_args
            if s.startswith("{") and "error" in json.loads(s)
        ]
        assert any(r["error"]["code"] == -32700 for r in error_responses)

    def test_notification_no_response_in_stdio(self, tmp_path: Path) -> None:
        """Une notification (pas de 'id') ne génère pas de print() de réponse."""
        server = _make_server(tmp_path)
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        ]
        fake_stdin = StringIO("\n".join(lines) + "\n")

        # Correction : MagicMock gère print(..., flush=True) sans planter
        # On extrait les args positionnels via call_args_list
        with patch("sys.stdin", fake_stdin), patch("builtins.print") as mock_print:
            server.serve_stdio()

        printed_args = [c[0][0] for c in mock_print.call_args_list if c[0]]
        responses = [
            json.loads(s) for s in printed_args
            if isinstance(s, str) and s.startswith("{")
        ]
        # La notification ne doit pas apparaître comme réponse (pas de 'id')
        notif_responses = [r for r in responses if r.get("id") is None and "result" in r]
        assert len(notif_responses) == 0
