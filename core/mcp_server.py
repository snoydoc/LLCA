# -*- coding: utf-8-sig -*-
"""
mcp_server.py — LCCA MCP Server V7.2 (Sprint REFACTO-01 refactorisé).

Serveur MCP V7.2 — JSON-RPC 2.0 over stdio.
Lifecycle + dispatch + stdio uniquement.
Les handlers _tool_* sont dans McpToolHandlers (mcp_tool_handlers.py).
Les schémas _TOOLS sont dans mcp_tools_schema.py.
Les constantes JSON-RPC sont dans mcp_types.py.

23 tools exposes (PROJ-04) + 1 (PROJ-UI-02) = 24 :
  memory_search, memory_store, project_search, edit_batch, sandbox_run,
  evaluate_quality, analyze_error, generate_spec, validate_spec,
  web_search, web_cache_stats, educator_status, llm_chat,
  project_list, project_create, project_open, project_close,
  project_archive, project_switch, project_get_context,
  project_save_context, project_healthcheck, project_compact_history,
  inspiration_generate
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import MCP_AUDIT_LOG, MCP_PROTOCOL_VERSION, SANDBOX_MODE, WORKSPACE_DIR
from utils.safe_path import PathSecurityError
from utils.telemetry import MetricTimer, log_metric

from core.mcp_types        import (  # noqa: F401 — re-export
    _JSONRPC, _ERR_PARSE, _ERR_INVALID_REQ, _ERR_METHOD_NOT_FOUND,
    _ERR_INVALID_PARAMS, _ERR_INTERNAL, _ERR_SECURITY, _ERR_TOOL_FAILED,
)
from core.mcp_tools_schema import _TOOLS
from core.mcp_tool_handlers import McpToolHandlers

log = logging.getLogger("lcca.mcp_server")


class McpServer(McpToolHandlers):
    """
    Serveur MCP V7.2 — JSON-RPC 2.0 over stdio.
    Hérite de McpToolHandlers pour les 23 _tool_* (PROJ-04).
    """

    def __init__(
        self,
        memory_engine=None,
        edit_batch=None,
        sandbox_engine=None,
        evaluator=None,
        error_analyzer=None,
        ast_indexer=None,
        workspace: Optional[Path] = None,
        spec_generator=None,
        spec_validator=None,
    ) -> None:
        self._workspace = workspace or WORKSPACE_DIR
        self._initialized = False

        if memory_engine is None:
            from core.memory_engine import MemoryEngine
            memory_engine = MemoryEngine()
        self._memory = memory_engine

        if edit_batch is None:
            from core.mcp_edit_batch import McpEditBatch
            edit_batch = McpEditBatch(workspace=self._workspace)
        self._edit_batch = edit_batch

        if sandbox_engine is None:
            from core.sandbox_engine import SandboxEngine
            sandbox_engine = SandboxEngine(workspace=self._workspace, mode=SANDBOX_MODE)
        self._sandbox = sandbox_engine

        if evaluator is None:
            from core.code_evaluator import CodeEvaluator
            evaluator = CodeEvaluator(threshold=60)
        self._evaluator = evaluator

        if error_analyzer is None:
            from core.error_analyzer import ErrorAnalyzer
            error_analyzer = ErrorAnalyzer()
        self._error_analyzer = error_analyzer

        if ast_indexer is None:
            from core.ast_indexer import ASTIndexer
            ast_indexer = ASTIndexer(workspace=self._workspace)
        self._indexer = ast_indexer

        self._spec_generator = spec_generator
        self._spec_validator  = spec_validator

        # Mode Projets (PROJ-04) — injectes ou instancies lazy via McpHandlersProjects
        self._project_manager = None
        self._project_lock    = None
        self._project_orch    = None

        try:
            self._indexer.index_repository()
        except Exception:
            pass

        MCP_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

    # ── Spec Layer helpers (instanciation lazy) ───────────────────────────────

    def _get_spec_validator(self):
        if self._spec_validator is None:
            from core.spec_validator import SpecValidatorService
            self._spec_validator = SpecValidatorService()
        return self._spec_validator

    def _get_spec_generator(self):
        if self._spec_generator is None:
            from config import OLLAMA_MODEL, SPEC_MAX_TOKENS, SPEC_TIMEOUT
            from core.llm_generator import LLMGenerator
            from core.cognitive_patterns import SpecDirectPattern
            from core.spec_generator import SpecGeneratorService
            # SPEC-01 : 1 seul appel LLM (SpecDirectPattern) au lieu de 2
            # BUGFIX : SPEC_MAX_TOKENS=1500 (spec complète 8 sections) + SPEC_TIMEOUT=360s
            llm = LLMGenerator(model=OLLAMA_MODEL, timeout=SPEC_TIMEOUT, max_tokens=SPEC_MAX_TOKENS)
            self._spec_generator = SpecGeneratorService(
                direct_pattern=SpecDirectPattern(llm),
                validator=self._get_spec_validator(),
            )
        return self._spec_generator

    # ── Entrée principale ─────────────────────────────────────────────────────

    def handle(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        req_id   = request.get("id")
        method   = request.get("method", "")
        params   = request.get("params") or {}
        is_notif = req_id is None

        log.debug("MCP request: method=%s id=%s", method, req_id)
        self._audit(method, params, req_id)

        if method == "initialize":
            return self._handle_initialize(req_id, params)
        if method == "notifications/initialized":
            self._initialized = True
            return None
        if method == "tools/list":
            return self._handle_tools_list(req_id)
        if method == "tools/call":
            if not self._initialized:
                return self._error_response(
                    req_id, _ERR_INVALID_REQ,
                    "Serveur non initialisé — envoyer 'initialize' d'abord"
                )
            return self._handle_tools_call(req_id, params, emit_notification=self._emit_notification)
        if method == "ping":
            return self._ok(req_id, {"pong": True})
        if is_notif:
            return None
        return self._error_response(req_id, _ERR_METHOD_NOT_FOUND, f"Méthode inconnue : {method}")

    # ── Lifecycle handlers ────────────────────────────────────────────────────

    def _handle_initialize(self, req_id, params):
        self._initialized = False
        result = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools":     {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts":   {"listChanged": False},
            },
            "serverInfo": {"name": "lcca-v7-mcp", "version": "7.2.0"},
        }
        log.info("MCP initialize -- protocol=%s", MCP_PROTOCOL_VERSION)
        return self._ok(req_id, result)

    def _handle_tools_list(self, req_id):
        return self._ok(req_id, {"tools": _TOOLS})

    def _handle_tools_call(self, req_id, params, emit_notification=None):
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}

        # UI-07 : pour llm_chat, on passe un callback emit_token qui émet
        # des notifications JSON-RPC sans id (push server→client).
        def make_emit_token(req_id_capture):
            def _emit(token: str):
                if emit_notification:
                    emit_notification({
                        "jsonrpc": _JSONRPC,
                        "method":  "lcca/token",
                        "params":  {"req_id": req_id_capture, "token": token},
                    })
            return _emit

        handler_map = {
            "memory_search":    self._tool_memory_search,
            "memory_store":     self._tool_memory_store,
            "project_search":   self._tool_project_search,
            "edit_batch":       self._tool_edit_batch,
            "sandbox_run":      self._tool_sandbox_run,
            "evaluate_quality": self._tool_evaluate_quality,
            "analyze_error":    self._tool_analyze_error,
            "generate_spec":    self._tool_generate_spec,
            "validate_spec":    self._tool_validate_spec,
            "web_search":       self._tool_web_search,
            "web_cache_stats":  self._tool_web_cache_stats,   # WEB-03
            "educator_status":  self._tool_educator_status,   # ED-03
            "llm_chat":         self._tool_llm_chat,
            # Mode Projets — PROJ-04
            "project_list":            self._tool_project_list,
            "project_create":          self._tool_project_create,
            "project_open":            self._tool_project_open,
            "project_close":           self._tool_project_close,
            "project_archive":         self._tool_project_archive,
            "project_switch":          self._tool_project_switch,
            "project_get_context":     self._tool_project_get_context,
            "project_save_context":    self._tool_project_save_context,
            "project_healthcheck":     self._tool_project_healthcheck,
            "project_compact_history": self._tool_project_compact_history,
            # PROJ-UI-02
            "inspiration_generate":     self._tool_inspiration_generate,
        }

        handler = handler_map.get(tool_name)
        if handler is None:
            return self._error_response(
                req_id, _ERR_METHOD_NOT_FOUND,
                f"Tool inconnu : '{tool_name}'. Disponibles : {list(handler_map.keys())}"
            )

        with MetricTimer("mcp_tool_duration", {"tool": tool_name}):
            try:
                # llm_chat reçoit emit_token pour le streaming réel (UI-07)
                if tool_name == "llm_chat":
                    result = handler(arguments, emit_token=make_emit_token(req_id))
                else:
                    result = handler(arguments)
                log_metric("mcp_tool_calls_total", 1, {"tool": tool_name, "success": True})
                return self._ok(
                    req_id,
                    {"content": [{"type": "text", "text": json.dumps(
                        result, ensure_ascii=False, default=str
                    )}]},
                )
            except PathSecurityError as exc:
                log_metric("mcp_tool_calls_total", 1, {"tool": tool_name, "success": False})
                log.warning("MCP security error [%s]: %s", tool_name, exc)
                return self._error_response(req_id, _ERR_SECURITY, str(exc))
            except (ValueError, TypeError, KeyError) as exc:
                log_metric("mcp_tool_calls_total", 1, {"tool": tool_name, "success": False})
                return self._error_response(req_id, _ERR_INVALID_PARAMS, str(exc))
            except Exception as exc:  # pragma: no cover
                log_metric("mcp_tool_calls_total", 1, {"tool": tool_name, "success": False})
                log.exception("MCP tool error [%s]", tool_name)
                return self._error_response(req_id, _ERR_INTERNAL, str(exc))

    # ── Helpers JSON-RPC ──────────────────────────────────────────────────────

    @staticmethod
    def _ok(req_id, result):
        return {"jsonrpc": _JSONRPC, "id": req_id, "result": result}

    @staticmethod
    def _error_response(req_id, code, message, data=None):
        err: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": _JSONRPC, "id": req_id, "error": err}

    def _audit(self, method, params, req_id):
        try:
            entry = {
                "_ts":         datetime.now(timezone.utc).isoformat(),
                "method":      method,
                "req_id":      req_id,
                "params_keys": list(params.keys()) if isinstance(params, dict) else [],
            }
            with MCP_AUDIT_LOG.open("a", encoding="utf-8") as f:  # utf-8 : JSON ASCII-safe
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
        except Exception:
            pass

    def _emit_notification(self, notification: dict) -> None:
        """UI-07 : émet une notification JSON-RPC push (sans id) sur stdout."""
        try:
            print(json.dumps(notification, ensure_ascii=False), flush=True)
        except Exception as exc:
            log.warning("emit_notification failed: %s", exc)

    def serve_stdio(self) -> None:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(encoding="utf-8")
            except Exception:
                pass

        log.info("LCCA MCP Server V7.2 -- ecoute sur stdio")
        # Message de présence non-JSON-RPC : signal pour le bridge Node.js que le process
        # est prêt. Les clients MCP stricts peuvent ignorer cette ligne (non JSON-RPC 2.0).
        print(json.dumps({"lcca": "ready", "protocol": MCP_PROTOCOL_VERSION}), flush=True)

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                print(json.dumps(self._error_response(None, _ERR_PARSE, "JSON invalide : %s" % exc)), flush=True)
                continue
            if not isinstance(request, dict):
                print(json.dumps(self._error_response(None, _ERR_INVALID_REQ, "La requête doit être un objet JSON")), flush=True)
                continue
            try:
                response = self.handle(request)
            except Exception:  # pragma: no cover
                response = self._error_response(
                    request.get("id"), _ERR_INTERNAL, "Erreur interne non gérée",
                    data=traceback.format_exc()[-500:],
                )
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)


def main() -> None:
    # Force stderr en UTF-8 pour eviter la corruption des caracteres accentues
    # quand Node.js lit le stderr Python sur Windows (CP1252 par defaut).
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    McpServer().serve_stdio()


if __name__ == "__main__":
    main()
