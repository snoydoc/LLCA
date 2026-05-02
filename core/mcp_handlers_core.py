# -*- coding: utf-8-sig -*-
"""
mcp_handlers_core.py — REFACTO-10
Extrait de mcp_tool_handlers.py : 7 handlers tools de base.

Responsabilité unique : handlers memory_search, memory_store, project_search,
edit_batch, sandbox_run, evaluate_quality, analyze_error.

McpHandlersCore est un mixin pur : aucun __init__, aucun lifecycle.
Suppose que self._memory, self._edit_batch, self._sandbox, self._evaluator,
self._error_analyzer, self._indexer, self._workspace sont définis par McpServer.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from utils.safe_path import PathSecurityError, safe_path

log = logging.getLogger("lcca.mcp_handlers_core")


class McpHandlersCore:
    """
    Mixin portant les 7 handlers tools de base.

    Attributs attendus du parent McpServer :
        self._memory, self._edit_batch, self._sandbox, self._evaluator,
        self._error_analyzer, self._indexer, self._workspace
    """

    def _tool_memory_search(self, args: Dict) -> Dict:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ValueError("'query' est requis et ne peut pas être vide")
        n    = int(args.get("n", 5))
        wing = str(args.get("wing", "lcca"))
        results = self._memory.search(query=query, wing=wing, n=n)
        return {
            collection: [
                {
                    "id":       e.id,
                    "content":  e.content,
                    "metadata": e.metadata,
                    "distance": e.distance,
                }
                for e in entries
            ]
            for collection, entries in results.items()
        }

    def _tool_memory_store(self, args: Dict) -> Dict:
        collection = str(args.get("collection", "")).strip()
        payload    = args.get("payload")
        if not collection:
            raise ValueError("'collection' est requis")
        if not isinstance(payload, dict):
            raise TypeError("'payload' doit être un objet JSON (dict)")
        result = self._memory.store(collection=collection, payload=payload)
        return {
            "stored":     result.stored,
            "collection": result.collection,
            "entry_id":   result.entry_id,
            "reason":     result.reason,
        }

    def _tool_project_search(self, args: Dict) -> Dict:
        query     = str(args.get("query", "")).strip()
        file_path = args.get("file_path")
        if not query:
            raise ValueError("'query' est requis")
        if file_path:
            safe_path(str(file_path), self._workspace)
        clean   = query.strip().rstrip("()")
        symbols = self._indexer.symbols_table.get(clean, [])
        sym_results = [
            {
                "name":       s.name,
                "type":       s.type,
                "file":       s.file,
                "line":       s.line,
                "docstring":  s.docstring,
                "is_private": s.is_private,
            }
            for s in symbols
        ]
        file_results: List[str] = []
        if not sym_results:
            query_lower = query.lower()
            for rel_path in self._indexer.files:
                if query_lower in rel_path.lower():
                    file_results.append(rel_path)
        return {
            "query":     query,
            "symbols":   sym_results,
            "files":     file_results,
            "n_symbols": len(sym_results),
            "n_files":   len(file_results),
        }

    def _tool_edit_batch(self, args: Dict) -> Dict:
        files = args.get("files")
        if not isinstance(files, list):
            raise TypeError("'files' doit être une liste d'opérations")
        if not files:
            raise ValueError("'files' ne peut pas être vide")
        for op in files:
            p = op.get("path", "")
            if p:
                safe_path(str(p), self._workspace)
        result = self._edit_batch.apply(files)
        if result.get("success"):
            try:
                self._indexer.index_repository()
            except Exception:
                pass
        else:
            log.warning(
                "edit_batch ECHEC : %s | rolled_back=%s",
                result.get("error", "erreur inconnue"),
                result.get("rolled_back"),
            )
        return result

    def _tool_sandbox_run(self, args: Dict) -> Dict:
        from config import SANDBOX_TIMEOUT
        code = args.get("code")
        if not code or not isinstance(code, str):
            raise ValueError("'code' est requis (string Python)")
        timeout = int(args.get("timeout", SANDBOX_TIMEOUT))
        if timeout <= 0:
            raise ValueError("'timeout' doit être strictement positif")
        success, stdout, stderr, exit_code = self._sandbox.run(code=code, timeout=timeout)
        return {
            "success":   success,
            "stdout":    stdout,
            "stderr":    stderr,
            "exit_code": exit_code,
        }

    def _tool_evaluate_quality(self, args: Dict) -> Dict:
        code = args.get("code")
        if not code or not isinstance(code, str):
            raise ValueError("'code' est requis (string Python)")
        filename = str(args.get("filename", "<generated>"))
        result = self._evaluator.evaluate(code=code, filename=filename)
        return result.to_dict()

    def _tool_analyze_error(self, args: Dict) -> Dict:
        error_type    = str(args.get("error_type", "Exception"))
        error_message = str(args.get("error_message", ""))
        file_path_str = str(args.get("file_path", "unknown"))
        source        = str(args.get("source", ""))
        if file_path_str and file_path_str != "unknown":
            try:
                safe_path(file_path_str, self._workspace)
            except PathSecurityError:
                pass
        exc_class = {
            "SyntaxError":           SyntaxError,
            "ImportError":           ImportError,
            "ModuleNotFoundError":   ModuleNotFoundError,
            "AttributeError":        AttributeError,
            "NameError":             NameError,
        }.get(error_type, Exception)
        try:
            if exc_class is SyntaxError:
                synthetic_exc = SyntaxError(error_message)
                synthetic_exc.lineno = None
                synthetic_exc.msg    = error_message
                synthetic_exc.text   = source[:100] if source else ""
            else:
                synthetic_exc = exc_class(error_message)
        except Exception:
            synthetic_exc = Exception(error_message)
        report    = self._error_analyzer.analyze(
            error=synthetic_exc, file_path=file_path_str, source=source
        )
        fix_prompt = self._error_analyzer.generate_fix_prompt(report=report, context=source)
        return {
            "error_type":  report.error_type,
            "file":        report.file,
            "line":        report.line,
            "message":     report.message,
            "suggestion":  report.suggestion,
            "severity":    report.severity,
            "auto_fixable": report.auto_fixable,
            "fix_prompt":  fix_prompt,
        }
