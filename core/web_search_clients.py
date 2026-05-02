# -*- coding: utf-8-sig -*-
"""
web_search_clients.py — Clients moteurs de recherche (REFACTO-19).

Extrait de web_search_engines.py pour separation des responsabilites.
Contient : BaseSearchClient ABC + _DdgLiteClient + _BraveSearchClient + _WikipediaClient.

MultiEngineSearchClient reste dans web_search_engines.py (orchestration).
Retro-compat : web_search_engines.py re-exporte les 3 classes.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

from core.web_search_types import SearchHit

log = logging.getLogger("lcca.web_search_engines")

_HTTP_TIMEOUT = 15   # secondes — plus court que le fetcher (15s vs 30s)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


# ── ABC ───────────────────────────────────────────────────────────────────────

class BaseSearchClient(ABC):
    """Interface commune de tous les clients moteurs."""
    name: str = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        """
        Retourne une liste de SearchHit.
        Ne leve jamais d'exception — retourne [] en cas d'erreur.
        """


# ── Client 1 : DuckDuckGo Lite ────────────────────────────────────────────────

class _DdgLiteClient(BaseSearchClient):
    """
    DuckDuckGo Lite — POST HTML, sans cle API, respectueux vie privee.
    Parser regex sur les classes CSS actuelles de DDG Lite.
    Fragile si DDG change son HTML — d'ou la cascade.
    """
    name = "duckduckgo"
    _URL = "https://lite.duckduckgo.com/lite/"

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        try:
            params = urllib.parse.urlencode({"q": query, "kl": "fr-fr"})
            req = urllib.request.Request(
                self._URL,
                data    = params.encode("utf-8"),
                headers = {**_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                method  = "POST",
            )
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return self._parse(raw, max_results)
        except Exception as exc:
            log.warning("DDG search failed: %s", exc)
            return []

    def _parse(self, html_text: str, max_results: int) -> list[SearchHit]:
        hits: list[SearchHit] = []

        link_re    = re.compile(
            r'<a[^>]+class="[^"]*result-link[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )
        snippet_re = re.compile(
            r'<td[^>]+class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</td>',
            re.DOTALL | re.IGNORECASE,
        )

        links    = link_re.findall(html_text)
        snippets = snippet_re.findall(html_text)

        for i, (url, title_raw) in enumerate(links[:max_results]):
            title   = html.unescape(re.sub(r"<[^>]+>", "", title_raw)).strip()
            snippet = ""
            if i < len(snippets):
                snippet = html.unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()
            if url.startswith("http") and "duckduckgo.com" not in url:
                hits.append(SearchHit(
                    title=title or url, url=url,
                    snippet=snippet, source_engine=self.name,
                ))

        # Fallback si parsing principal echoue
        if not hits:
            # Fallback ameliore (WEB-03) : filtrage heuristique des liens parasites
            fallback = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
            for url, title_raw in fallback.findall(html_text):
                if "duckduckgo.com" in url or "duck.co" in url:
                    continue
                if any(x in url for x in ("doubleclick", "google-analytics", "facebook.com", "twitter.com", "t.co/")):
                    continue
                parsed_parts = url.split("/")
                if len(parsed_parts) < 3:
                    continue
                title = html.unescape(re.sub(r"<[^>]+>", "", title_raw)).strip()
                if not title or len(title) < 8:
                    continue
                hits.append(SearchHit(
                    title=title, url=url,
                    source_engine=self.name,
                ))
                if len(hits) >= max_results:
                    break

        log.debug("DDG: %d hits", len(hits))
        return hits


# ── Client 2 : Brave Search ───────────────────────────────────────────────────

class _BraveSearchClient(BaseSearchClient):
    """
    Brave Search — API publique JSON, sans cle API requise (2000 req/mois).
    Si BRAVE_SEARCH_API_KEY est defini, quota monte a 2000 req/jour.
    """
    name = "brave"
    _URL = "https://search.brave.com/search"

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        try:
            params  = urllib.parse.urlencode({
                "q":      query,
                "source": "web",
                "count":  max_results,
            })
            url     = f"{self._URL}?{params}"
            headers = {
                **_HEADERS,
                "Accept": "application/json",
            }
            api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
            if api_key:
                headers["X-Subscription-Token"] = api_key

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            results = data.get("web", {}).get("results", [])
            hits = []
            for r in results[:max_results]:
                hits.append(SearchHit(
                    title         = r.get("title", ""),
                    url           = r.get("url", ""),
                    snippet       = r.get("description", ""),
                    source_engine = self.name,
                ))
            log.debug("Brave: %d hits", len(hits))
            return hits

        except Exception as exc:
            log.warning("Brave search failed: %s", exc)
            return []


# ── Client 3 : Wikipedia ─────────────────────────────────────────────────────

class _WikipediaClient(BaseSearchClient):
    """
    Wikipedia REST API — dernier recours pour requetes encyclopediques.
    Zero cle API, JSON natif, fiable, quota illimite.
    """
    name = "wikipedia"
    _SEARCH_URL  = "https://fr.wikipedia.org/w/api.php"
    _SUMMARY_URL = "https://fr.wikipedia.org/api/rest_v1/page/summary"

    _ENCYCLOPEDIC_KEYWORDS = (
        "qu'est-ce que", "c'est quoi", "definition", "definir",
        "histoire de", "origine de", "comment fonctionne", "expliquer",
        "qui est", "biographie", "invente par",
        # variantes avec accents (conserves pour le matching)
        "définition", "définir", "inventé par",
    )

    @classmethod
    def is_encyclopedic(cls, query: str) -> bool:
        """True si la requete est encyclopedique et beneficiera de Wikipedia."""
        q = query.lower()
        return any(kw in q for kw in cls._ENCYCLOPEDIC_KEYWORDS)

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        try:
            params = urllib.parse.urlencode({
                "action":    "opensearch",
                "search":    query,
                "limit":     max_results,
                "format":    "json",
                "namespace": 0,
            })
            url = f"{self._SEARCH_URL}?{params}"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if len(data) < 4:
                return []

            titles       = data[1]
            descriptions = data[2]
            urls         = data[3]

            hits = []
            for i, (title, url, desc) in enumerate(zip(titles, urls, descriptions)):
                if i >= max_results:
                    break
                hits.append(SearchHit(
                    title         = title,
                    url           = url,
                    snippet       = desc,
                    source_engine = self.name,
                ))

            log.debug("Wikipedia: %d hits", len(hits))
            return hits

        except Exception as exc:
            log.warning("Wikipedia search failed: %s", exc)
            return []
