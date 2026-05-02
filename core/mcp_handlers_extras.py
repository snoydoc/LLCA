# -*- coding: utf-8-sig -*-
"""
mcp_handlers_extras.py — REFACTO-10
Extrait de mcp_tool_handlers.py : handlers educator_status, web_search, web_cache_stats.

Responsabilité unique : handlers outils complémentaires (ED-03, UI-06, WEB-03).

McpHandlersExtras est un mixin pur : aucun __init__, aucun lifecycle.
Suppose que self._context (dict optionnel) et self._educator_agent (optionnel)
sont accessibles sur McpServer.
"""
from __future__ import annotations

import logging
from typing import Dict

log = logging.getLogger("lcca.mcp_handlers_extras")


class McpHandlersExtras:
    """
    Mixin portant les 3 handlers tools complémentaires :
      - educator_status (ED-03)
      - web_search (UI-06)
      - web_cache_stats (WEB-03)

    Attributs attendus (tous optionnels, défaut None/{}):
        self._context, self._educator_agent
    """

    # ── ED-03 : educator_status ──────────────────────────────────────────────

    def _tool_educator_status(self, args: Dict) -> Dict:
        """
        ED-03 — Expose le dernier CurationResult de l'EducatorAgent via MCP.

        Recherche l'agent dans self._context si disponible, sinon dans self.
        Retourne 'idle' si aucune curation n'a encore été lancée.
        """
        context = getattr(self, "_context", {}) or {}
        agent   = context.get("educator_agent") or getattr(self, "_educator_agent", None)
        if agent is None:
            return {"status": "not_configured", "result": None}
        result = agent.last_result()
        if result is None:
            return {"status": "idle", "result": None}
        return {
            "status":           "ok",
            "dry_run":          result.dry_run,
            "repos_processed":  result.repos_processed,
            "files_fetched":    result.files_fetched,
            "files_filtered":   result.files_filtered,
            "skills_ingested":  result.skills_ingested,
            "context_ingested": result.context_ingested,
            "errors":           result.errors,
        }

    # ── UI-06 : web_search ───────────────────────────────────────────────────

    def _tool_web_search(self, args: Dict) -> Dict:
        query = str(args.get("query", "")).strip()
        if not query:
            raise ValueError("'query' est requis et ne peut pas être vide")
        max_results = int(args.get("max_results", 5))
        from core.web_search import WebSearchEngine
        engine = WebSearchEngine(max_results=max_results)
        result = engine.search(query)
        return result.to_dict()

    # ── WEB-03 : web_cache_stats ─────────────────────────────────────────────

    def _tool_web_cache_stats(self, args: Dict) -> Dict:
        """
        Sprint WEB-03 — Inspection et gestion du cache de recherche web.

        Actions :
          - stats         : nombre d'entrées, taille totale, chemin du cache
          - clear_expired : supprime les entrées expirées
          - invalidate    : invalide une entrée spécifique (par query exacte)
        """
        from core.web_search import WebSearchEngine
        action = str(args.get("action", "stats")).strip()
        query  = str(args.get("query", "")).strip()

        engine = WebSearchEngine()
        cache  = engine._cache

        if action == "stats":
            stats = cache.stats()
            return {
                "action":    "stats",
                "entries":   stats["entries"],
                "size_kb":   stats["size_kb"],
                "cache_dir": stats["cache_dir"],
            }

        if action == "clear_expired":
            removed = cache.clear_expired()
            return {
                "action":  "clear_expired",
                "removed": removed,
                "message": f"{removed} entrée(s) expirée(s) supprimée(s)",
            }

        if action == "invalidate":
            if not query:
                raise ValueError("'query' est requis pour action=invalidate")
            deleted = cache.invalidate(query)
            return {
                "action":  "invalidate",
                "query":   query,
                "deleted": deleted,
                "message": (
                    f"Entrée '{query[:40]}' supprimée du cache."
                    if deleted else
                    f"Aucune entrée trouvée pour '{query[:40]}'."
                ),
            }

        raise ValueError(
            f"Action inconnue : '{action}'. Valeurs valides : stats, clear_expired, invalidate"
        )
