# -*- coding: utf-8-sig -*-
"""
web_search_engines.py — Facade MultiEngineSearchClient (REFACTO-19).

Clients moteurs (BaseSearchClient, _DdgLiteClient, _BraveSearchClient,
_WikipediaClient) delégués à web_search_clients.py.

Rétro-compat : les 3 classes privées restent importables depuis ce module.
    from core.web_search_engines import _DdgLiteClient   # toujours OK
"""
from __future__ import annotations

import logging

from core.web_search_clients import (  # noqa: F401 — réexports rétrocompat
    BaseSearchClient,
    _BraveSearchClient,
    _DdgLiteClient,
    _WikipediaClient,
)
from core.web_search_types import SearchHit

log = logging.getLogger("lcca.web_search_engines")


# ── Orchestrateur multi-moteurs ───────────────────────────────────────────────

class MultiEngineSearchClient:
    """
    Orchestre la cascade de moteurs et déduplique les résultats.

    Stratégie :
        1. DDG Lite     — toujours tenté en premier
        2. Brave Search — si DDG retourne < min_hits résultats ou échoue
        3. Wikipedia    — si requête encyclopédique OU les deux premiers échouent

    Déduplication : URLs normalisées (sans www, sans trailing slash, sans fragment).
    Traçabilité   : chaque SearchHit porte son source_engine.
    """

    _ENGINE_ORDER = [_DdgLiteClient, _BraveSearchClient]

    def __init__(self, min_hits: int = 3) -> None:
        self._min_hits = min_hits

    def search(self, query: str, max_results: int = 5) -> tuple[list[SearchHit], list[str]]:
        """
        Retourne (hits_dédupliqués, engines_used).
        """
        seen_urls:    set[str]        = set()
        all_hits:     list[SearchHit] = []
        engines_used: list[str]       = []

        for EngineClass in self._ENGINE_ORDER:
            if len(all_hits) >= max_results:
                break
            engine = EngineClass()
            try:
                hits     = engine.search(query, max_results=max_results)
                new_hits = [h for h in hits if self._normalize_url(h.url) not in seen_urls]
                for h in new_hits:
                    seen_urls.add(self._normalize_url(h.url))
                    all_hits.append(h)
                if hits:
                    engines_used.append(engine.name)
                    log.info("engine=%s: %d hits (%d nouveaux)", engine.name, len(hits), len(new_hits))
            except Exception as exc:
                log.warning("engine=%s crash inattendu: %s", EngineClass.name, exc)

        # Wikipedia en dernier recours ou si requête encyclopédique
        if len(all_hits) < self._min_hits or _WikipediaClient.is_encyclopedic(query):
            wiki = _WikipediaClient()
            try:
                wiki_hits = wiki.search(query, max_results=max_results)
                new_wiki  = [h for h in wiki_hits if self._normalize_url(h.url) not in seen_urls]
                for h in new_wiki:
                    seen_urls.add(self._normalize_url(h.url))
                    all_hits.append(h)
                if wiki_hits:
                    engines_used.append(wiki.name)
                    log.info("engine=wikipedia: %d hits (%d nouveaux)", len(wiki_hits), len(new_wiki))
            except Exception as exc:
                log.warning("engine=wikipedia crash: %s", exc)

        return all_hits[:max_results], engines_used

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalise une URL pour déduplication (lowercase, sans www, sans fragment)."""
        url = url.lower().rstrip("/").split("#")[0]
        if url.startswith("https://www."):
            url = "https://" + url[12:]
        elif url.startswith("http://www."):
            url = "http://" + url[11:]
        return url
