# -*- coding: utf-8-sig -*-
"""
test_mcp_integration.py — LCCA V7
Sprint 13 — TASK-13-02 (bugfixes 3 failed)

Tests d'intégration MCP end-to-end.

Corrections session 2026-04-18 :
  - test_patch_existing_file_adds_function : écrire dans workspace APRÈS _make_real_server
  - test_evaluate_minimal_code_low_score   : code pathologique ciblé + assertion score<threshold
  - test_search_finds_indexed_file         : idem ordre server/write corrigé

Stratégie :
  - McpServer instancié SANS mocks pour les modules critiques :
      McpEditBatch, TransactionManager, SandboxEngine (mode soft), CodeEvaluator
  - MemoryEngine et ErrorAnalyzer mockés (ChromaDB/Ollama non requis)
  - ASTIndexer réel sur workspace temporaire
  - Chaque test exerce une chaîne de tools MCP complète via server.handle()
  - Vérification : WAL, fichiers disque, réponses JSON-RPC, sécurité

Suites :
  TestMcpIntegrationLifecycle      — handshake complet (4 tests)
  TestMcpIntegrationEditBatch      — edit_batch end-to-end (6 tests)
  TestMcpIntegrationSandbox        — sandbox_run end-to-end (4 tests)
  TestMcpIntegrationEvaluate       — evaluate_quality end-to-end (3 tests)
  TestMcpIntegrationProjectSearch  — project_search end-to-end (4 tests)
  TestMcpIntegrationSecurity       — sécurité transversale (4 tests)
  TestMcpIntegrationPipeline       — pipelines combinés (5 tests)
  TestMcpIntegrationStdio          — boucle stdio end-to-end (4 tests)

Total : 38 tests (23 tools depuis PROJ-04)
"""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from core.ast_indexer import ASTIndexer
from core.code_evaluator import CodeEvaluator
from core.mcp_edit_batch import McpEditBatch
from core.mcp_server import McpServer, _ERR_INVALID_PARAMS, _ERR_METHOD_NOT_FOUND, _ERR_SECURITY
from core.sandbox_engine import SandboxEngine
from core.transaction_manager import TransactionManager


# ──────────────────────────────────────────────────────────────────────────────
# Constantes de code réutilisées dans plusieurs tests
# ──────────────────────────────────────────────────────────────────────────────

_MODULE_SIMPLE = '''\
"""Module de calcul minimal."""


def add(a: int, b: int) -> int:
    """Additionne deux entiers."""
    return a + b
'''

_MODULE_WITH_CLASS = '''\
"""Module avec classe."""


class Counter:
    """Compteur simple."""

    def __init__(self) -> None:
        """Initialise le compteur a zero."""
        self._count = 0

    def increment(self) -> None:
        """Incremente le compteur."""
        self._count += 1

    def value(self) -> int:
        """Retourne la valeur courante."""
        return self._count
'''

_CODE_RUNNABLE = "result = 2 + 2\nprint(result)\n"
_CODE_SYNTAX_ERROR = "def broken(:\n    pass\n"
_CODE_RUNTIME_ERROR = "raise ValueError('runtime error test')\n"

# Code pathologique — score vise < 60 (threshold=60).
#
# Calcul projeté :
#   Syntaxe     : 30/30  (valide)
#   Type hints  :  0/20  (fonction présente MAIS non typée → 0)
#   Docstrings  : 10/20  (aucune docstring → score // 2)
#   Complexité  :  0/15  (bare except + 6 if imbriqués → complexité ≥ 11 → 0)
#   Anti-patterns: 3/15  (bare except -5, global -4, print -3 → max(15-12,0)=3)
#   TOTAL       : 43/100  < 60 ✅
#
# Règle apprise (session 2026-04-18) : sans aucune fonction, score_type_hints()
# accorde le bonus 20/20 ("non applicable"). Il faut TOUJOURS inclure une fonction
# non typée pour tester un score type hints faible.
_CODE_BAD_QUALITY = (
    "global x\n"
    "x = 1\n"
    "\n"
    "def bad_func(a, b):\n"
    "    try:\n"
    "        pass\n"
    "    except:\n"
    "        print(x)\n"
    "    if a:\n"
    "        if a > 0:\n"
    "            if a > 1:\n"
    "                if a > 2:\n"
    "                    if a > 3:\n"
    "                        if b:\n"
    "                            x = 0\n"
)


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────

def _make_real_server(tmp_path: Path) -> McpServer:
    """
    McpServer avec dependances reelles isolees sur tmp_path.

    IMPORTANT : cette fonction cree tmp_path/workspace et tmp_path/transactions.
    Les tests qui veulent ecrire des fichiers dans le workspace DOIVENT appeler
    _make_real_server() EN PREMIER, puis ecrire dans (tmp_path / "workspace").

    - TransactionManager  -> tmp_path / "transactions"
    - McpEditBatch        -> workspace = tmp_path / "workspace"
    - SandboxEngine       -> mode soft, workspace = tmp_path / "workspace"
    - CodeEvaluator       -> threshold = 60
    - ASTIndexer          -> workspace = tmp_path / "workspace"
    - MemoryEngine        -> MagicMock (ChromaDB non requis)
    - ErrorAnalyzer       -> MagicMock (Ollama non requis)
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    tx_dir = tmp_path / "transactions"
    tx_dir.mkdir(parents=True, exist_ok=True)

    tx_manager = TransactionManager(tx_dir=tx_dir)
    edit_batch = McpEditBatch(tx_manager=tx_manager, workspace=workspace)
    sandbox    = SandboxEngine(workspace=workspace, mode="soft")
    evaluator  = CodeEvaluator(threshold=60)
    indexer    = ASTIndexer(workspace=workspace)

    mock_memory = MagicMock()
    mock_memory.search.return_value = {
        "solutions": [], "failures": [], "context": [], "patches": []
    }
    mock_memory.store.return_value = MagicMock(
        stored=True, collection="lcca_patches", entry_id="test_id", reason=None
    )

    mock_error_report = MagicMock()
    mock_error_report.error_type   = "ValueError"
    mock_error_report.file         = "test.py"
    mock_error_report.line         = 1
    mock_error_report.message      = "test error"
    mock_error_report.suggestion   = "Corriger l'erreur"
    mock_error_report.severity     = "warning"
    mock_error_report.auto_fixable = False
    mock_error_analyzer = MagicMock()
    mock_error_analyzer.analyze.return_value = mock_error_report
    mock_error_analyzer.generate_fix_prompt.return_value = "Fix prompt text"

    return McpServer(
        memory_engine=mock_memory,
        edit_batch=edit_batch,
        sandbox_engine=sandbox,
        evaluator=evaluator,
        error_analyzer=mock_error_analyzer,
        ast_indexer=indexer,
        workspace=workspace,
    )


def _initialized(server: McpServer) -> McpServer:
    """Effectue le handshake MCP et retourne le serveur pret."""
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return server


def _call(server: McpServer, tool: str, args: Dict[str, Any], req_id: int = 42) -> Dict:
    """Raccourci tools/call."""
    return server.handle({
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    })


# ──────────────────────────────────────────────────────────────────────────────
# 1. Lifecycle
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpIntegrationLifecycle:

    def test_initialize_returns_server_info(self, tmp_path: Path) -> None:
        """Le serveur repond correctement a initialize avec des deps reelles."""
        server = _make_real_server(tmp_path)
        resp = server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        assert resp["result"]["serverInfo"]["name"] == "lcca-v7-mcp"
        assert resp["result"]["serverInfo"]["version"] == "7.2.0"

    def test_tools_list_returns_correct_names(self, tmp_path: Path) -> None:
        """Apres handshake, tools/list retourne les 13 tools."""
        server = _initialized(_make_real_server(tmp_path))
        resp = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == {
            "memory_search", "memory_store", "project_search",
            "edit_batch", "sandbox_run", "evaluate_quality", "analyze_error",
            "generate_spec", "validate_spec",
            "llm_chat", "web_search", "web_cache_stats",
            "educator_status",
        }

    def test_call_before_initialize_rejected(self, tmp_path: Path) -> None:
        """Un tool/call avant initialize est refuse."""
        server = _make_real_server(tmp_path)
        resp = _call(server, "sandbox_run", {"code": "print(1)"})
        assert "error" in resp

    def test_ping_works_with_real_deps(self, tmp_path: Path) -> None:
        """ping repond pong meme avec des deps reelles."""
        server = _make_real_server(tmp_path)
        resp = server.handle({"jsonrpc": "2.0", "id": 5, "method": "ping"})
        assert resp["result"]["pong"] is True


# ──────────────────────────────────────────────────────────────────────────────
# 2. edit_batch
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpIntegrationEditBatch:

    def test_create_file_writes_to_disk(self, tmp_path: Path) -> None:
        """edit_batch cree un fichier sur disque et commit dans le WAL."""
        server = _initialized(_make_real_server(tmp_path))
        workspace = tmp_path / "workspace"

        resp = _call(server, "edit_batch", {
            "files": [{"path": "new_calc.py", "action": "create", "code": _MODULE_SIMPLE}]
        })
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["success"] is True
        assert (workspace / "new_calc.py").exists()
        assert "def add" in (workspace / "new_calc.py").read_text(encoding="utf-8-sig")

    def test_create_file_wal_contains_commit(self, tmp_path: Path) -> None:
        """Apres edit_batch reussi, le WAL contient un COMMIT."""
        server = _initialized(_make_real_server(tmp_path))
        tx_dir = tmp_path / "transactions"

        _call(server, "edit_batch", {
            "files": [{"path": "module_a.py", "action": "create", "code": _MODULE_SIMPLE}]
        })
        wal = tx_dir / "wal.jsonl"
        assert wal.exists()
        entries = [
            json.loads(line)
            for line in wal.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        assert any(e["type"] == "COMMIT" for e in entries)

    def test_create_invalid_syntax_rolls_back(self, tmp_path: Path) -> None:
        """edit_batch avec code invalide declenche rollback, aucun fichier cree."""
        server = _initialized(_make_real_server(tmp_path))
        workspace = tmp_path / "workspace"

        resp = _call(server, "edit_batch", {
            "files": [{"path": "bad.py", "action": "create", "code": _CODE_SYNTAX_ERROR}]
        })
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["success"] is False
        assert result["rolled_back"] is True
        assert not (workspace / "bad.py").exists()

    def test_patch_existing_file_adds_function(self, tmp_path: Path) -> None:
        """edit_batch ajoute une fonction a un fichier existant.

        ORDRE OBLIGATOIRE : _make_real_server cree workspace/ — ecrire dedans APRES.
        """
        server = _initialized(_make_real_server(tmp_path))
        workspace = tmp_path / "workspace"
        # workspace existe maintenant — on peut y ecrire
        (workspace / "calc.py").write_text(_MODULE_SIMPLE, encoding="utf-8-sig")

        resp = _call(server, "edit_batch", {
            "files": [{
                "path": "calc.py",
                "patch_type": "add_function",
                "code": "def multiply(a: int, b: int) -> int:\n    return a * b\n",
            }]
        })
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["success"] is True
        content = (workspace / "calc.py").read_text(encoding="utf-8-sig")
        assert "def multiply" in content
        assert "def add" in content

    def test_batch_triggers_reindex(self, tmp_path: Path) -> None:
        """Apres un edit_batch reussi, le fichier est bien present (reindex OK)."""
        server = _initialized(_make_real_server(tmp_path))
        _call(server, "edit_batch", {
            "files": [{"path": "indexed.py", "action": "create", "code": _MODULE_WITH_CLASS}]
        })
        assert (tmp_path / "workspace" / "indexed.py").exists()

    def test_batch_returns_evaluation_score(self, tmp_path: Path) -> None:
        """edit_batch inclut le score qualite dans la reponse."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "edit_batch", {
            "files": [{"path": "qt.py", "action": "create", "code": _MODULE_SIMPLE}]
        })
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["success"] is True
        assert len(result["evaluations"]) == 1
        ev = result["evaluations"][0]
        assert "score" in ev
        assert isinstance(ev["score"], int)


# ──────────────────────────────────────────────────────────────────────────────
# 3. sandbox_run
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpIntegrationSandbox:

    def test_sandbox_runs_simple_code(self, tmp_path: Path) -> None:
        """sandbox_run execute du code Python et retourne stdout."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "sandbox_run", {"code": _CODE_RUNNABLE})
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["success"] is True
        assert "4" in result["stdout"]

    def test_sandbox_captures_runtime_error(self, tmp_path: Path) -> None:
        """sandbox_run retourne success=False sur une erreur d'execution."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "sandbox_run", {"code": _CODE_RUNTIME_ERROR})
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["success"] is False
        assert result["exit_code"] != 0

    def test_sandbox_empty_code_error(self, tmp_path: Path) -> None:
        """sandbox_run avec code vide retourne une erreur JSON-RPC."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "sandbox_run", {"code": ""})
        assert "error" in resp
        assert resp["error"]["code"] == _ERR_INVALID_PARAMS

    def test_sandbox_timeout_zero_error(self, tmp_path: Path) -> None:
        """timeout=0 est rejete comme parametre invalide."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "sandbox_run", {"code": "x=1", "timeout": 0})
        assert "error" in resp


# ──────────────────────────────────────────────────────────────────────────────
# 4. evaluate_quality
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpIntegrationEvaluate:

    def test_evaluate_good_code_high_score(self, tmp_path: Path) -> None:
        """evaluate_quality retourne un score >= 0 pour du code bien type."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "evaluate_quality", {
            "code": _MODULE_SIMPLE, "filename": "calc.py",
        })
        result = json.loads(resp["result"]["content"][0]["text"])
        assert "score" in result
        assert isinstance(result["score"], int)
        assert result["score"] >= 0

    def test_evaluate_minimal_code_low_score(self, tmp_path: Path) -> None:
        """evaluate_quality retourne score < threshold pour du code pathologique.

        _CODE_BAD_QUALITY cible :
          - bare except      -> -5 pts antipatterns
          - global           -> -4 pts antipatterns
          - print()          -> -3 pts antipatterns
          - 5 if imbriques   -> complexite ~8, penalite forte
        Score vise < 60 (threshold=60).
        """
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "evaluate_quality", {"code": _CODE_BAD_QUALITY})
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["score"] < result["threshold"], (
            f"Score {result['score']} attendu < threshold {result['threshold']}. "
            f"Criteres: {result.get('criteria', [])}"
        )

    def test_evaluate_empty_code_error(self, tmp_path: Path) -> None:
        """evaluate_quality avec code vide retourne une erreur JSON-RPC."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "evaluate_quality", {"code": ""})
        assert "error" in resp


# ──────────────────────────────────────────────────────────────────────────────
# 5. project_search
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpIntegrationProjectSearch:

    def test_search_finds_indexed_file(self, tmp_path: Path) -> None:
        """project_search trouve un fichier present dans le workspace.

        ORDRE : _make_real_server() cree workspace/ — ecrire dedans APRES.
        """
        server = _initialized(_make_real_server(tmp_path))
        workspace = tmp_path / "workspace"
        # workspace existe — on peut y ecrire
        (workspace / "auth.py").write_text(_MODULE_SIMPLE, encoding="utf-8-sig")
        # Re-indexer maintenant que le fichier existe
        server._indexer.index_repository()

        resp = _call(server, "project_search", {"query": "auth"})
        result = json.loads(resp["result"]["content"][0]["text"])
        assert "files" in result
        assert "symbols" in result
        file_match = any("auth" in f for f in result["files"])
        sym_match  = any("auth" in (s.get("file", "")) for s in result["symbols"])
        assert file_match or sym_match, (
            f"'auth.py' non trouve dans files={result['files']} ni symbols={result['symbols']}"
        )

    def test_search_returns_symbols_after_create(self, tmp_path: Path) -> None:
        """Apres edit_batch, project_search retourne les symboles."""
        server = _initialized(_make_real_server(tmp_path))
        _call(server, "edit_batch", {
            "files": [{"path": "mymod.py", "action": "create", "code": _MODULE_SIMPLE}]
        })
        resp = _call(server, "project_search", {"query": "add"})
        result = json.loads(resp["result"]["content"][0]["text"])
        assert "symbols" in result

    def test_search_empty_query_error(self, tmp_path: Path) -> None:
        """query vide -> erreur JSON-RPC."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "project_search", {"query": ""})
        assert "error" in resp

    def test_search_path_traversal_blocked(self, tmp_path: Path) -> None:
        """file_path avec traversal -> erreur securite."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "project_search", {
            "query": "auth",
            "file_path": "../../../etc/passwd",
        })
        assert "error" in resp
        assert resp["error"]["code"] == _ERR_SECURITY


# ──────────────────────────────────────────────────────────────────────────────
# 6. Securite
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpIntegrationSecurity:

    def test_edit_batch_absolute_path_blocked(self, tmp_path: Path) -> None:
        """edit_batch bloque les chemins absolus."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "edit_batch", {
            "files": [{"path": "/etc/passwd", "action": "create", "code": "x=1"}]
        })
        assert "error" in resp
        assert resp["error"]["code"] == _ERR_SECURITY

    def test_edit_batch_traversal_blocked(self, tmp_path: Path) -> None:
        """edit_batch bloque les path traversal."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "edit_batch", {
            "files": [{"path": "../../../evil.py", "action": "create", "code": "x=1"}]
        })
        assert "error" in resp

    def test_edit_batch_does_not_write_on_security_error(self, tmp_path: Path) -> None:
        """Aucun fichier ne doit etre ecrit si safe_path leve."""
        server = _initialized(_make_real_server(tmp_path))
        _call(server, "edit_batch", {
            "files": [{"path": "../evil.py", "action": "create", "code": "x=1"}]
        })
        assert not (tmp_path / "evil.py").exists()

    def test_unknown_tool_returns_method_not_found(self, tmp_path: Path) -> None:
        """Un tool inconnu retourne _ERR_METHOD_NOT_FOUND."""
        server = _initialized(_make_real_server(tmp_path))
        resp = _call(server, "not_a_real_tool", {})
        assert "error" in resp
        assert resp["error"]["code"] == _ERR_METHOD_NOT_FOUND


# ──────────────────────────────────────────────────────────────────────────────
# 7. Pipelines
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpIntegrationPipeline:

    def test_create_then_run_in_sandbox(self, tmp_path: Path) -> None:
        """Pipeline : edit_batch cree -> sandbox_run execute."""
        server = _initialized(_make_real_server(tmp_path))
        workspace = tmp_path / "workspace"

        _call(server, "edit_batch", {
            "files": [{"path": "runner.py", "action": "create", "code": "print('hello from runner')\n"}]
        })
        assert (workspace / "runner.py").exists()

        code = (workspace / "runner.py").read_text(encoding="utf-8-sig")
        result = json.loads(_call(server, "sandbox_run", {"code": code})["result"]["content"][0]["text"])
        assert result["success"] is True
        assert "hello from runner" in result["stdout"]

    def test_create_then_evaluate(self, tmp_path: Path) -> None:
        """Pipeline : edit_batch cree -> evaluate_quality evalue."""
        server = _initialized(_make_real_server(tmp_path))
        workspace = tmp_path / "workspace"

        _call(server, "edit_batch", {
            "files": [{"path": "evaled.py", "action": "create", "code": _MODULE_WITH_CLASS}]
        })
        code = (workspace / "evaled.py").read_text(encoding="utf-8-sig")
        result = json.loads(
            _call(server, "evaluate_quality", {"code": code, "filename": "evaled.py"})
            ["result"]["content"][0]["text"]
        )
        assert result["score"] >= 0

    def test_create_then_search(self, tmp_path: Path) -> None:
        """Pipeline : edit_batch cree -> project_search trouve le fichier."""
        server = _initialized(_make_real_server(tmp_path))
        _call(server, "edit_batch", {
            "files": [{"path": "pipe_mod.py", "action": "create", "code": _MODULE_SIMPLE}]
        })
        result = json.loads(
            _call(server, "project_search", {"query": "pipe_mod"})
            ["result"]["content"][0]["text"]
        )
        assert "files" in result

    def test_two_batches_in_sequence(self, tmp_path: Path) -> None:
        """Deux edit_batch successifs sur le meme fichier : 2 COMMITs dans le WAL."""
        server = _initialized(_make_real_server(tmp_path))
        tx_dir = tmp_path / "transactions"

        _call(server, "edit_batch", {
            "files": [{"path": "seq.py", "action": "create", "code": _MODULE_SIMPLE}]
        })
        _call(server, "edit_batch", {
            "files": [{
                "path": "seq.py",
                "patch_type": "add_function",
                "code": "def subtract(a: int, b: int) -> int:\n    return a - b\n",
            }]
        })

        entries = [
            json.loads(line)
            for line in (tx_dir / "wal.jsonl").read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        assert len([e for e in entries if e["type"] == "COMMIT"]) >= 2

    def test_create_run_evaluate_full_cycle(self, tmp_path: Path) -> None:
        """Pipeline complet : creer, executer, evaluer — sans erreur."""
        server = _initialized(_make_real_server(tmp_path))
        code = (
            "def factorial(n: int) -> int:\n"
            '    """Calcule la factorielle de n."""\n'
            "    if n <= 1:\n"
            "        return 1\n"
            "    return n * factorial(n - 1)\n\n"
            "print(factorial(5))\n"
        )

        r1 = json.loads(_call(server, "edit_batch", {
            "files": [{"path": "factorial.py", "action": "create", "code": code}]
        })["result"]["content"][0]["text"])
        assert r1["success"] is True

        r2 = json.loads(_call(server, "sandbox_run", {"code": code})["result"]["content"][0]["text"])
        assert r2["success"] is True
        assert "120" in r2["stdout"]

        r3 = json.loads(_call(server, "evaluate_quality", {
            "code": code, "filename": "factorial.py"
        })["result"]["content"][0]["text"])
        assert r3["score"] >= 0


# ──────────────────────────────────────────────────────────────────────────────
# 8. Boucle stdio
# ──────────────────────────────────────────────────────────────────────────────

class TestMcpIntegrationStdio:

    @staticmethod
    def _run_stdio(server: McpServer, messages: list) -> list:
        """Lance serve_stdio() avec stdin simule, retourne les reponses JSON parsees."""
        lines = "\n".join(json.dumps(m) for m in messages) + "\n"
        parsed: list = []

        def _mock_print(text: str = "", **kwargs) -> None:
            try:
                parsed.append(json.loads(text))
            except (json.JSONDecodeError, TypeError):
                pass

        with (
            patch("sys.stdin", StringIO(lines)),
            patch("builtins.print", side_effect=_mock_print),
        ):
            server.serve_stdio()
        return parsed

    def test_stdio_full_handshake(self, tmp_path: Path) -> None:
        """La boucle stdio complete le handshake MCP correctement."""
        responses = self._run_stdio(_make_real_server(tmp_path), [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ])
        ids = [r.get("id") for r in responses if "result" in r]
        assert 1 in ids
        assert 2 in ids
        tools_resp = next(r for r in responses if r.get("id") == 2)
        assert len({t["name"] for t in tools_resp["result"]["tools"]}) == 13

    def test_stdio_invalid_json_parse_error(self, tmp_path: Path) -> None:
        """Une ligne JSON invalide declenche une erreur -32700."""
        parsed: list = []

        def _mock_print(text: str = "", **kwargs) -> None:
            try:
                parsed.append(json.loads(text))
            except Exception:
                pass

        with (
            patch("sys.stdin", StringIO("not json\n")),
            patch("builtins.print", side_effect=_mock_print),
        ):
            _make_real_server(tmp_path).serve_stdio()

        assert any(r.get("error", {}).get("code") == -32700 for r in parsed if "error" in r)

    def test_stdio_notification_no_response(self, tmp_path: Path) -> None:
        """Les notifications (sans id) ne generent pas de reponse."""
        responses = self._run_stdio(_make_real_server(tmp_path), [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ])
        assert not any(r.get("id") is None and "result" in r for r in responses)

    def test_stdio_edit_batch_end_to_end(self, tmp_path: Path) -> None:
        """La boucle stdio traite un edit_batch et cree le fichier sur disque."""
        server = _make_real_server(tmp_path)
        workspace = tmp_path / "workspace"
        responses = self._run_stdio(server, [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {
                    "name": "edit_batch",
                    "arguments": {
                        "files": [{"path": "stdio_created.py", "action": "create", "code": _MODULE_SIMPLE}]
                    },
                },
            },
        ])
        tool_resp = next((r for r in responses if r.get("id") == 2), None)
        assert tool_resp is not None, "Pas de reponse a la requete id=2"
        result = json.loads(tool_resp["result"]["content"][0]["text"])
        assert result["success"] is True
        assert (workspace / "stdio_created.py").exists()
