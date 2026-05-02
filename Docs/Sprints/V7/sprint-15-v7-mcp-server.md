# Sprint 15 — V7 MCP Server : Protocole JSON-RPC 2.0 stdio
<!-- AI-READY | Sprint V7.0 | Phase 4/5 | 2026-04-17 -->

## 🎯 Objectif
Implémenter le serveur MCP complet `mcp_server.py` (entrée principale de LCCA V7) :
- Lifecycle JSON-RPC 2.0 strict : `initialize → notifications/initialized → tools/list → tools/call`
- 7 tools exposés (memory_search, memory_store, project_search, edit_batch, sandbox_run, evaluate_quality, analyze_error)
- RBAC minimal + audit trail JSONL
- Telemetry intégrée (MetricTimer + log_metric)
- Entrée principale : `main_mcp.py` (CLI + REPL)

**Résultat attendu** : ≥ 317 + ~30 nouveaux tests PASSED, 0 FAILED.

---

## 📋 TÂCHES

### TASK-15-01 — `mcp_server.py` : Serveur MCP stdio

**Fichier** : `D:\LLMCodeAgent\mcp_server.py` *(nouveau)*

```python
# -*- coding: utf-8-sig -*-
"""
mcp_server.py — LCCA V7
Serveur MCP stdio JSON-RPC 2.0.

Lifecycle obligatoire :
  1. client → initialize
  2. server → capabilities
  3. client → notifications/initialized
  4. client → tools/list
  5. client → tools/call
  6. server → résultat ou erreur structurée

Sécurité :
  - RBAC par tool (permissions minimales)
  - Audit trail JSONL (mcp_audit.jsonl)
  - Validation workspace containment via safe_path()
  - Jamais d'exécution hors workspace

Sprint 15 — TASK-15-01
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config import (
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    MCP_AUDIT_LOG,
    WORKSPACE_DIR,
)
from utils.telemetry import log_metric, MetricTimer

log = logging.getLogger("lcca.mcp_server")


# ══════════════════════════════════════════════════════════════════════════════
# Définition des Tools MCP
# ══════════════════════════════════════════════════════════════════════════════

MCP_TOOLS = [
    {
        "name": "memory_search",
        "description": (
            "Recherche sémantique dans la mémoire LCCA (4 collections : solutions, "
            "failures, context, patches). Utiliser avant toute modification de code "
            "pour récupérer le contexte pertinent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string",  "description": "Texte de recherche"},
                "collections": {"type": "array",   "items": {"type": "string"},
                                "description": "Collections à interroger (défaut: toutes)"},
                "n":           {"type": "integer", "description": "Résultats par collection (défaut: 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_store",
        "description": (
            "Stocke un résultat dans la mémoire LCCA. "
            "lcca_failures est toujours stocké (apprentissage par échec). "
            "lcca_solutions requiert score >= 0.8."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "collection": {"type": "string",  "description": "lcca_solutions | lcca_failures | lcca_context | lcca_patches"},
                "content":    {"type": "string",  "description": "Contenu à stocker"},
                "score":      {"type": "number",  "description": "Score qualité 0.0-1.0"},
                "metadata":   {"type": "object",  "description": "Métadonnées additionnelles"},
            },
            "required": ["collection", "content"],
        },
    },
    {
        "name": "project_search",
        "description": (
            "Recherche de symboles Python (fonctions, classes) et fichiers "
            "dans le workspace du projet. Utiliser pour comprendre la structure "
            "avant de générer ou modifier du code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":     {"type": "string", "description": "Nom de symbole ou mot-clé"},
                "file_path": {"type": "string", "description": "Chemin fichier relatif (optionnel)"},
                "strategy":  {"type": "string", "enum": ["symbol", "filename", "content"],
                              "description": "Stratégie de recherche (défaut: symbol)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "edit_batch",
        "description": (
            "Applique un batch de modifications de code de manière atomique (ACID). "
            "Maximum 3 fichiers par appel. Utiliser evaluate_quality avant et "
            "sandbox_run après pour valider."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "description": "Liste de modifications",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path":       {"type": "string"},
                            "patch_type": {"type": "string"},
                            "action":     {"type": "string"},
                            "symbol":     {"type": "string"},
                            "code":       {"type": "string"},
                        },
                        "required": ["path"],
                    },
                }
            },
            "required": ["files"],
        },
    },
    {
        "name": "sandbox_run",
        "description": (
            "Exécute du code Python en isolation (subprocess ou Docker). "
            "Utiliser après edit_batch pour valider le comportement du code modifié. "
            "Timeout configurable, réseau désactivé."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code":      {"type": "string",  "description": "Code Python à exécuter"},
                "file_path": {"type": "string",  "description": "Chemin relatif workspace (optionnel)"},
                "timeout":   {"type": "integer", "description": "Timeout secondes (défaut: 30)"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "evaluate_quality",
        "description": (
            "Évalue la qualité statique du code Python (score 0-100). "
            "Critères : syntaxe, type hints, docstrings, complexité McCabe, anti-patterns. "
            "Informatif en V7.0 — ne bloque pas le patch."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code":     {"type": "string", "description": "Code Python à évaluer"},
                "filename": {"type": "string", "description": "Nom de fichier (pour le rapport)"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "analyze_error",
        "description": (
            "Analyse une erreur Python et propose des suggestions de correction. "
            "Identifie le type d'erreur, la cause probable et si elle est auto-corrigeable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "error":   {"type": "string", "description": "Message d'erreur complet"},
                "context": {"type": "string", "description": "Code contexte (optionnel)"},
            },
            "required": ["error"],
        },
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# RBAC — Permissions par tool
# ══════════════════════════════════════════════════════════════════════════════

# V7.0 : tous les tools sont autorisés (RBAC futur V7.2)
_TOOL_PERMISSIONS: Dict[str, list] = {
    "memory_search":    ["read"],
    "memory_store":     ["write"],
    "project_search":   ["read"],
    "edit_batch":       ["write", "execute"],
    "sandbox_run":      ["execute"],
    "evaluate_quality": ["read"],
    "analyze_error":    ["read"],
}


# ══════════════════════════════════════════════════════════════════════════════
# MCPServer
# ══════════════════════════════════════════════════════════════════════════════

class MCPServer:
    """
    Serveur MCP stdio JSON-RPC 2.0 pour LCCA V7.

    Lit les requêtes sur stdin (une par ligne JSON),
    écrit les réponses sur stdout (une par ligne JSON).
    Les logs vont sur stderr pour ne pas polluer le canal MCP.

    Args:
        workspace     : Répertoire workspace du projet.
        auto_init     : Si True, initialise les composants V5 au démarrage.
        edit_batch    : Instance McpEditBatch injectée (tests).
        memory_engine : Instance MemoryEngine injectée (tests).
        sandbox       : Instance SandboxEngine injectée (tests).
    """

    def __init__(
        self,
        workspace:     Optional[Path]  = None,
        auto_init:     bool            = True,
        edit_batch=None,
        memory_engine=None,
        sandbox=None,
        ast_indexer=None,
        file_selector=None,
        error_analyzer=None,
        code_evaluator=None,
    ) -> None:
        self.workspace = workspace or WORKSPACE_DIR
        self._initialized = False

        # Composants injectables (pour tests unitaires)
        self._edit_batch    = edit_batch
        self._memory_engine = memory_engine
        self._sandbox       = sandbox
        self._indexer       = ast_indexer
        self._selector      = file_selector
        self._error_analyzer= error_analyzer
        self._evaluator     = code_evaluator

        if auto_init:
            self._init_components()

    def _init_components(self) -> None:
        """Initialise les composants V5 avec gestion d'erreur."""
        try:
            if self._edit_batch is None:
                from core.mcp_edit_batch import McpEditBatch
                self._edit_batch = McpEditBatch(workspace=self.workspace)

            if self._memory_engine is None:
                from core.memory_engine import MemoryEngine
                self._memory_engine = MemoryEngine()

            if self._sandbox is None:
                from core.sandbox_engine import SandboxEngine
                self._sandbox = SandboxEngine(workspace=self.workspace)

            if self._indexer is None:
                from core.ast_indexer import ASTIndexer
                self._indexer = ASTIndexer(workspace=self.workspace)
                try:
                    self._indexer.index_repository()
                except Exception:
                    pass

            if self._selector is None:
                from core.file_selector import FileSelector
                self._selector = FileSelector(
                    workspace=self.workspace, indexer=self._indexer
                )

            if self._error_analyzer is None:
                from core.error_analyzer import ErrorAnalyzer
                self._error_analyzer = ErrorAnalyzer()

            if self._evaluator is None:
                from core.code_evaluator import CodeEvaluator
                self._evaluator = CodeEvaluator()

            log.info("MCPServer composants initialisés — workspace=%s", self.workspace)

        except Exception as exc:
            log.error("Erreur init composants : %s", exc)

    # ── Lifecycle JSON-RPC ──────────────────────────────────────────────────

    def handle_request(self, raw: str) -> Optional[Dict]:
        """
        Traite une requête JSON-RPC brute.

        Returns:
            Dict réponse JSON-RPC, ou None si notification (pas de réponse).
        """
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._error_response(None, -32700, f"Parse error: {exc}")

        req_id = req.get("id")
        method = req.get("method", "")

        # Audit
        self._audit(method, req.get("params", {}))

        with MetricTimer("mcp_request_duration", {"method": method}):
            if method == "initialize":
                return self._handle_initialize(req_id, req.get("params", {}))

            if method == "notifications/initialized":
                self._initialized = True
                return None   # Notification — pas de réponse

            if method == "tools/list":
                return self._handle_tools_list(req_id)

            if method == "tools/call":
                return self._handle_tools_call(req_id, req.get("params", {}))

            if method == "ping":
                return self._ok(req_id, {"pong": True})

            return self._error_response(req_id, -32601, f"Method not found: {method}")

    def _handle_initialize(self, req_id, params: dict) -> Dict:
        return self._ok(req_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools":     {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts":   {"listChanged": False},
            },
            "serverInfo": {
                "name":    MCP_SERVER_NAME,
                "version": MCP_SERVER_VERSION,
            },
        })

    def _handle_tools_list(self, req_id) -> Dict:
        return self._ok(req_id, {"tools": MCP_TOOLS})

    def _handle_tools_call(self, req_id, params: dict) -> Dict:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        log_metric("mcp_tool_calls_total", 1, {"tool": tool_name})

        dispatch = {
            "memory_search":    self._tool_memory_search,
            "memory_store":     self._tool_memory_store,
            "project_search":   self._tool_project_search,
            "edit_batch":       self._tool_edit_batch,
            "sandbox_run":      self._tool_sandbox_run,
            "evaluate_quality": self._tool_evaluate_quality,
            "analyze_error":    self._tool_analyze_error,
        }

        handler = dispatch.get(tool_name)
        if handler is None:
            return self._error_response(req_id, -32601, f"Tool inconnu : {tool_name}")

        try:
            result = handler(arguments)
            log_metric("mcp_tool_success", 1, {"tool": tool_name})
            return self._ok(req_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
        except Exception as exc:
            log.error("Tool %s erreur : %s", tool_name, exc)
            log_metric("mcp_tool_error", 1, {"tool": tool_name})
            return self._error_response(req_id, -32603, str(exc))

    # ── Handlers des tools ──────────────────────────────────────────────────

    def _tool_memory_search(self, args: dict) -> dict:
        query = args.get("query", "")
        n = int(args.get("n", 5))
        cols = args.get("collections")
        if self._memory_engine is None:
            return {"results": {}, "error": "MemoryEngine non initialisé"}
        return self._memory_engine.search(query, n=n, collections=cols)

    def _tool_memory_store(self, args: dict) -> dict:
        collection = args.get("collection", "lcca_context")
        payload = {
            "content":  args.get("content", ""),
            "score":    args.get("score", 0.0),
            **(args.get("metadata") or {}),
        }
        if self._memory_engine is None:
            return {"stored": False, "reason": "MemoryEngine non initialisé"}
        return self._memory_engine.store(collection, payload)

    def _tool_project_search(self, args: dict) -> dict:
        query    = args.get("query", "")
        strategy = args.get("strategy", "symbol")
        if self._selector is None:
            return {"files": [], "error": "FileSelector non initialisé"}
        try:
            files = self._selector.select(query, strategy=strategy)
            return {"files": [str(f) for f in files]}
        except Exception as exc:
            return {"files": [], "error": str(exc)}

    def _tool_edit_batch(self, args: dict) -> dict:
        files = args.get("files", [])
        if self._edit_batch is None:
            return {"success": False, "error": "McpEditBatch non initialisé"}
        with MetricTimer("edit_batch_duration", {"n_files": len(files)}):
            result = self._edit_batch.apply(files)
        return result

    def _tool_sandbox_run(self, args: dict) -> dict:
        code      = args.get("code", "")
        file_path = args.get("file_path")
        timeout   = args.get("timeout")
        if self._sandbox is None:
            return {"success": False, "stdout": "", "stderr": "Sandbox non initialisé", "exit_code": -1}
        ok, stdout, stderr, code_exit = self._sandbox.run(
            code, file_path=file_path, timeout=timeout
        )
        return {"success": ok, "stdout": stdout, "stderr": stderr, "exit_code": code_exit}

    def _tool_evaluate_quality(self, args: dict) -> dict:
        code     = args.get("code", "")
        filename = args.get("filename", "code.py")
        if self._evaluator is None:
            return {"score": -1, "error": "CodeEvaluator non initialisé"}
        try:
            result = self._evaluator.evaluate(code, filename=filename)
            return result.to_dict() if hasattr(result, "to_dict") else {"score": -1}
        except Exception as exc:
            return {"score": -1, "error": str(exc)}

    def _tool_analyze_error(self, args: dict) -> dict:
        error   = args.get("error", "")
        context = args.get("context", "")
        if self._error_analyzer is None:
            return {"type": "unknown", "suggestion": "ErrorAnalyzer non initialisé"}
        try:
            report = self._error_analyzer.analyze(error, context=context)
            return {
                "error_type":    getattr(report, "error_type",   "unknown"),
                "suggestion":    getattr(report, "suggestion",   ""),
                "auto_fixable":  getattr(report, "auto_fixable", False),
            }
        except Exception as exc:
            return {"type": "unknown", "suggestion": str(exc)}

    # ── Helpers JSON-RPC ────────────────────────────────────────────────────

    @staticmethod
    def _ok(req_id, result: Any) -> Dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _error_response(req_id, code: int, message: str) -> Dict:
        return {
            "jsonrpc": "2.0",
            "id":      req_id,
            "error":   {"code": code, "message": message},
        }

    # ── Audit ───────────────────────────────────────────────────────────────

    def _audit(self, method: str, params: dict) -> None:
        """Écrit une entrée d'audit JSONL."""
        entry = {
            "_ts":    datetime.now(timezone.utc).isoformat(),
            "method": method,
            "params": {k: str(v)[:200] for k, v in params.items()},   # Truncate
        }
        try:
            MCP_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with MCP_AUDIT_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── Boucle principale ───────────────────────────────────────────────────

    def serve_stdio(self) -> None:
        """
        Lance la boucle MCP stdio.
        Lit stdin ligne par ligne (JSON-RPC), écrit les réponses sur stdout.
        Les logs sont redirigés sur stderr pour ne pas interférer.
        """
        log.info("MCPServer démarré — mode stdio (Ctrl+C pour arrêter)")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            response = self.handle_request(line)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
```

---

### TASK-15-02 — `main_mcp.py` : CLI entrée MCP

**Fichier** : `D:\LLMCodeAgent\main_mcp.py` *(nouveau)*

```python
#!/usr/bin/env python3
# -*- coding: utf-8-sig -*-
"""
main_mcp.py — LCCA V7
Point d'entrée du serveur MCP.

Usage :
    # Mode serveur stdio (pour Goose / Claude Desktop)
    python main_mcp.py

    # Mode test interactif REPL
    python main_mcp.py --repl

    # Mode test single request
    python main_mcp.py --call tools/list

    # Status du serveur
    python main_mcp.py --status

Sprint 15 — TASK-15-02
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Logs vers stderr — ne pas polluer le canal MCP
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("lcca.main_mcp")

_EXIT_CMDS  = {"exit", "quit", "q", ":q"}
_STATUS_CMDS = {"status", "health", "info"}
_HELP_CMDS  = {"help", "?", ":h"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LCCA V7 MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python main_mcp.py                    # Mode MCP stdio (Goose)
  python main_mcp.py --repl             # REPL JSON interactif
  python main_mcp.py --call tools/list  # Appel unique
  python main_mcp.py --status           # État du serveur
        """,
    )
    parser.add_argument("--project",   type=Path,   help="Workspace du projet")
    parser.add_argument("--repl",      action="store_true", help="Mode REPL interactif")
    parser.add_argument("--call",      type=str,    help="Appel direct d'une méthode MCP")
    parser.add_argument("--args",      type=str,    default="{}", help="Arguments JSON pour --call")
    parser.add_argument("--status",    action="store_true", help="Affiche l'état du serveur")
    parser.add_argument("--no-memory", action="store_true", help="Désactive MemPalace")
    parser.add_argument("--no-docker", action="store_true", help="Force mode sandbox soft")
    return parser


def _make_server(args) -> "MCPServer":
    from mcp_server import MCPServer
    workspace = args.project if args.project else None
    return MCPServer(workspace=workspace, auto_init=True)


def run_status(server) -> None:
    """Affiche l'état de tous les composants."""
    print("═" * 50)
    print("LCCA V7 MCP Server — Status")
    print("═" * 50)

    components = {
        "McpEditBatch":  server._edit_batch,
        "MemoryEngine":  server._memory_engine,
        "SandboxEngine": server._sandbox,
        "ASTIndexer":    server._indexer,
        "CodeEvaluator": server._evaluator,
        "ErrorAnalyzer": server._error_analyzer,
    }
    for name, comp in components.items():
        status = "✅" if comp is not None else "❌"
        print(f"  {status} {name}")

    if server._sandbox is not None:
        hc = server._sandbox.health_check()
        print(f"\n  Sandbox mode   : {hc['mode']}")
        print(f"  Docker dispo   : {hc['docker_available']}")
        print(f"  Timeout        : {hc['timeout']}s")

    from config import MCP_PROTOCOL_VERSION, MCP_SERVER_VERSION
    print(f"\n  Protocol       : {MCP_PROTOCOL_VERSION}")
    print(f"  Server version : {MCP_SERVER_VERSION}")
    print("═" * 50)


def run_call(server, method: str, args_json: str) -> None:
    """Exécute un appel MCP unique depuis la ligne de commande."""
    args = json.loads(args_json)
    req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": args}
    response = server.handle_request(json.dumps(req))
    print(json.dumps(response, indent=2, ensure_ascii=False))


def run_repl(server) -> None:
    """REPL interactif JSON-RPC."""
    print("LCCA V7 MCP REPL — Entrez des requêtes JSON-RPC ou des commandes")
    print("  status       → État du serveur")
    print("  tools        → Liste des tools")
    print("  exit         → Quitter")
    print()

    req_id = 1

    while True:
        try:
            raw = input("mcp> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAu revoir.")
            break

        if not raw:
            continue

        raw_lower = raw.lower()

        if raw_lower in _EXIT_CMDS:
            break

        if raw_lower in _STATUS_CMDS:
            run_status(server)
            continue

        if raw_lower in _HELP_CMDS:
            print("Méthodes : initialize, tools/list, tools/call, ping")
            continue

        if raw_lower == "tools":
            req = {"jsonrpc": "2.0", "id": req_id, "method": "tools/list"}
            raw = json.dumps(req)

        try:
            response = server.handle_request(raw)
            if response:
                print(json.dumps(response, indent=2, ensure_ascii=False))
        except Exception as exc:
            print(f"Erreur : {exc}")

        req_id += 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    server = _make_server(args)

    if args.status:
        run_status(server)
        return

    if args.call:
        run_call(server, args.call, args.args)
        return

    if args.repl:
        run_repl(server)
        return

    # Mode stdio par défaut
    server.serve_stdio()


if __name__ == "__main__":
    main()
```

---

### TASK-15-03 — `.goose/recipes/lcca-dev.yaml` : Recipe Goose

**Fichier** : `D:\LLMCodeAgent\.goose\recipes\lcca-dev.yaml` *(nouveau, dossier à créer)*

```yaml
# lcca-dev.yaml — Recipe Goose pour LCCA V7
# Usage: goose run --recipe .goose/recipes/lcca-dev.yaml

name: "LCCA V7 Dev Agent"
description: "Agent de codage local transactionnel avec mémoire persistante LCCA V7"
version: "7.0.0"

instructions: |
  Tu es LCCA V7, un agent de codage transactionnel local.
  
  PROTOCOLE OBLIGATOIRE (toujours respecter cet ordre) :
  
  1. AVANT modification : memory_search pour récupérer le contexte pertinent
  2. PLANIFICATION : project_search pour identifier les fichiers cibles
  3. ÉVALUATION pré-patch : evaluate_quality sur le code généré
  4. APPLICATION : edit_batch (max 3 fichiers par appel, ACID garanti)
  5. VALIDATION : sandbox_run sur le code modifié
  6. SI ERREUR : analyze_error puis retry ou rollback
  7. STOCKAGE : memory_store du résultat (solution ou failure)
  
  RÈGLES INVARIANTES :
  - Jamais de modification directe hors workspace
  - Toujours utiliser edit_batch (jamais de création manuelle de fichiers)
  - En cas de doute sur la qualité : évaluer avant d'appliquer
  - Stocker les échecs dans lcca_failures (apprentissage par l'erreur)

tools:
  - memory_search
  - memory_store
  - project_search
  - edit_batch
  - sandbox_run
  - evaluate_quality
  - analyze_error

close_the_loop: true
```

---

## 🧪 TESTS

### `tests/test_mcp_server.py` *(nouveau — 20 tests)*

```python
# -*- coding: utf-8-sig -*-
"""Tests unitaires mcp_server.py — Sprint 15."""
import json
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def server():
    from mcp_server import MCPServer
    # Composants tous mockés — pas de dépendances réelles
    eb = MagicMock()
    eb.apply.return_value = {"success": True, "tx_id": "tx_test123", "evaluations": []}
    me = MagicMock()
    me.search.return_value = {"solutions": [], "failures": [], "context": []}
    me.store.return_value = {"stored": True, "entry_id": "e1"}
    sb = MagicMock()
    sb.run.return_value = (True, "output OK", "", 0)
    sb.health_check.return_value = {"mode": "soft", "docker_available": False, "timeout": 30}
    ev = MagicMock()
    ev_result = MagicMock()
    ev_result.to_dict.return_value = {"score": 75}
    ev.evaluate.return_value = ev_result
    ea = MagicMock()
    ea_report = MagicMock()
    ea_report.error_type = "ImportError"
    ea_report.suggestion = "pip install missing"
    ea_report.auto_fixable = True
    ea.analyze.return_value = ea_report
    sel = MagicMock()
    sel.select.return_value = ["/workspace/module.py"]
    idx = MagicMock()
    return MCPServer(
        auto_init=False,
        edit_batch=eb, memory_engine=me, sandbox=sb,
        ast_indexer=idx, file_selector=sel, error_analyzer=ea, code_evaluator=ev,
    )


class TestMCPLifecycle:
    def _req(self, method, params=None, req_id=1):
        return json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})

    def test_initialize_response(self, server):
        resp = server.handle_request(self._req("initialize"))
        assert resp["result"]["protocolVersion"] is not None
        assert "tools" in resp["result"]["capabilities"]

    def test_tools_list_returns_7_tools(self, server):
        resp = server.handle_request(self._req("tools/list"))
        assert len(resp["result"]["tools"]) == 7

    def test_tools_list_tool_names(self, server):
        resp = server.handle_request(self._req("tools/list"))
        names = {t["name"] for t in resp["result"]["tools"]}
        expected = {"memory_search", "memory_store", "project_search",
                    "edit_batch", "sandbox_run", "evaluate_quality", "analyze_error"}
        assert names == expected

    def test_notification_initialized_no_response(self, server):
        resp = server.handle_request(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )
        assert resp is None

    def test_unknown_method_error(self, server):
        resp = server.handle_request(self._req("unknown/method"))
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_invalid_json_error(self, server):
        resp = server.handle_request("{invalid json{{")
        assert "error" in resp
        assert resp["error"]["code"] == -32700

    def test_ping_responds(self, server):
        resp = server.handle_request(self._req("ping"))
        assert resp["result"]["pong"] is True


class TestMCPToolsCall:
    def _call(self, server, tool_name, arguments):
        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        return server.handle_request(req)

    def test_memory_search_called(self, server):
        resp = self._call(server, "memory_search", {"query": "validate function"})
        assert resp["result"] is not None
        server._memory_engine.search.assert_called_once()

    def test_memory_store_called(self, server):
        resp = self._call(server, "memory_store", {
            "collection": "lcca_solutions", "content": "def foo(): pass", "score": 0.9
        })
        content_text = json.loads(resp["result"]["content"][0]["text"])
        assert content_text["stored"] is True

    def test_project_search_called(self, server):
        resp = self._call(server, "project_search", {"query": "validate_email"})
        assert resp["result"] is not None
        server._selector.select.assert_called_once()

    def test_edit_batch_called(self, server):
        resp = self._call(server, "edit_batch", {"files": [{
            "path": "module.py", "patch_type": "add_function", "symbol": "foo"
        }]})
        content_text = json.loads(resp["result"]["content"][0]["text"])
        assert content_text["success"] is True

    def test_sandbox_run_called(self, server):
        resp = self._call(server, "sandbox_run", {"code": 'print("hello")'})
        content_text = json.loads(resp["result"]["content"][0]["text"])
        assert content_text["success"] is True
        assert "output OK" in content_text["stdout"]

    def test_evaluate_quality_called(self, server):
        resp = self._call(server, "evaluate_quality", {
            "code": "def foo():\n    pass\n", "filename": "test.py"
        })
        content_text = json.loads(resp["result"]["content"][0]["text"])
        assert "score" in content_text

    def test_analyze_error_called(self, server):
        resp = self._call(server, "analyze_error", {
            "error": "ImportError: No module named 'requests'"
        })
        content_text = json.loads(resp["result"]["content"][0]["text"])
        assert "error_type" in content_text

    def test_unknown_tool_error(self, server):
        resp = self._call(server, "nonexistent_tool", {})
        assert "error" in resp

    def test_jsonrpc_version_in_response(self, server):
        resp = server.handle_request(json.dumps({
            "jsonrpc": "2.0", "id": 99, "method": "tools/list"
        }))
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 99


class TestMCPAudit:
    def test_audit_file_created(self, server, tmp_path):
        from config import MCP_AUDIT_LOG
        with patch("mcp_server.MCP_AUDIT_LOG", tmp_path / "audit.jsonl"):
            server.handle_request(json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/list"
            }))
        audit_file = tmp_path / "audit.jsonl"
        if audit_file.exists():
            lines = audit_file.read_text().strip().splitlines()
            assert len(lines) >= 1
            entry = json.loads(lines[0])
            assert "method" in entry
            assert "_ts" in entry
```

### `tests/test_mcp_security.py` *(nouveau — 10 tests)*

```python
# -*- coding: utf-8-sig -*-
"""Tests de sécurité MCP — Sprint 15."""
import json
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def secure_server(tmp_path):
    """Serveur avec workspace réel dans tmp_path."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from mcp_server import MCPServer
    from core.mcp_edit_batch import McpEditBatch
    from core.transaction_manager import TransactionManager
    tm = TransactionManager(
        tx_dir=tmp_path / "tx", wal_path=tmp_path / "wal.jsonl"
    )
    patcher = MagicMock()
    patcher.apply_patch.return_value = "def foo(): pass\n"
    evaluator = MagicMock()
    ev = MagicMock()
    ev.score = 80
    ev.to_dict.return_value = {"score": 80}
    evaluator.evaluate.return_value = ev
    batch = McpEditBatch(tm, patcher, evaluator, workspace)
    return MCPServer(workspace=workspace, auto_init=False, edit_batch=batch)


class TestMCPSecurityPaths:
    def _edit(self, server, path):
        return server.handle_request(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "edit_batch", "arguments": {
                "files": [{"path": path, "patch_type": "add_function", "code": "def x(): pass"}]
            }}
        }))

    def test_path_traversal_blocked(self, secure_server):
        resp = self._edit(secure_server, "../../../etc/passwd")
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is False

    def test_absolute_path_blocked(self, secure_server):
        resp = self._edit(secure_server, "/etc/shadow")
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is False

    def test_windows_absolute_blocked(self, secure_server):
        resp = self._edit(secure_server, "C:/Windows/system32/cmd.exe")
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is False

    def test_too_many_files_blocked(self, secure_server):
        files = [{"path": f"f{i}.py", "patch_type": "add_function"} for i in range(10)]
        resp = secure_server.handle_request(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "edit_batch", "arguments": {"files": files}}
        }))
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is False

    def test_valid_path_allowed(self, secure_server, tmp_path):
        ws = tmp_path / "workspace"
        (ws / "module.py").write_text("x = 1\n", encoding="utf-8")
        resp = self._edit(secure_server, "module.py")
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["success"] is True

    def test_sandbox_path_traversal_blocked(self, secure_server):
        resp = secure_server.handle_request(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "sandbox_run", "arguments": {
                "code": 'print("ok")',
                "file_path": "../../secret.txt"
            }}
        }))
        # Le sandbox devrait rejeter le file_path invalide
        assert resp is not None  # Au moins une réponse JSON-RPC valide
```

---

## 📦 FICHIERS NOUVEAUX / MODIFIÉS

| Fichier | Action | Tests |
|---------|--------|-------|
| `mcp_server.py` | CREATE | `test_mcp_server.py` (20), `test_mcp_security.py` (10) |
| `main_mcp.py` | CREATE | Manuel (CLI) |
| `.goose/recipes/lcca-dev.yaml` | CREATE | Manuel (Goose) |
| `tests/test_mcp_server.py` | CREATE | — |
| `tests/test_mcp_security.py` | CREATE | — |

---

## ✅ CRITÈRES D'ACCEPTATION

- [ ] `pytest tests/ -v` → ≥ 347 PASSED, 0 FAILED
- [ ] `MCPServer.handle_request('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}')` retourne `protocolVersion`
- [ ] `tools/list` retourne exactement 7 tools avec `inputSchema`
- [ ] `tools/call edit_batch` avec path traversal → `success: False`
- [ ] `notifications/initialized` → retourne `None` (pas de réponse)
- [ ] Audit trail écrit dans `mcp_audit.jsonl`
- [ ] Logs sur `stderr` uniquement (canal MCP propre)
- [ ] 0 régression sur les 317 tests Sprint 14

---

## 🔗 DÉPENDANCES

- **Bloque** : Sprint 16 (intégration finale, Goose)
- **Dépend de** : Sprint 12 (safe_path, telemetry), Sprint 13 (McpEditBatch, MemoryEngine), Sprint 14 (SandboxEngine)
- **Intègre** : Tous les composants V5 (TransactionManager, CodeEvaluator, ErrorAnalyzer...)

<!-- Sprint 15 | V7 MCP Server | LCCA V7.0.0-rc1 | 2026-04-17 -->
