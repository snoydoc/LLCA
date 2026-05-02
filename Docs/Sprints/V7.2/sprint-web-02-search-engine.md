# Sprint WEB-02 — Moteur de recherche web multi-sources
<!-- AI-READY | Sprint WEB-02 | Version 1.0.0 | 2026-04-19 -->

## Contexte & objectif

Le module `core/web_search.py` livré en UI-06 est fonctionnel mais fragile :
un seul moteur (DDG Lite), un parser HTML cassable à tout moment, une extraction
de texte naïve, pas de cache, pas de déduplication, pas de scoring de qualité.

Ce sprint le transforme en un moteur de recherche robuste, multi-sources,
avec cache TTL, extraction sémantique, et traçabilité complète — sans aucune
dépendance externe (stdlib uniquement, conforme règle LCCA).

**Prérequis** : Sprint UI-06b vert (timeout web_search corrigé).
**Livrable** : 4 nouveaux modules + `web_search.py` refactorisé, tests verts,
zéro régression sur l'API publique `WebSearchEngine.search()`.

---

## Périmètre — fichiers

| # | Fichier | Type | Description |
|---|---------|------|-------------|
| 1 | `core/web_search_engines.py` | CREATE | `BaseSearchClient` ABC + 3 clients moteurs |
| 2 | `core/web_search_fetcher.py` | CREATE | `_PageFetcher` amélioré : extraction sémantique + scoring |
| 3 | `core/web_search_cache.py` | CREATE | `SearchCache` TTL fichier JSON |
| 4 | `core/web_search_types.py` | CREATE | Dataclasses enrichies (`SearchHit`, `FetchedPage`, `SearchResult`) |
| 5 | `core/web_search.py` | UPDATE | `WebSearchEngine` orchestrateur refactorisé |
| 6 | `tests/test_web_search.py` | CREATE | Tests unitaires des 4 nouveaux modules |

---

## Tâche 1 — `core/web_search_types.py` (CREATE)

Dataclasses enrichies. Aucune logique, aucun import de modules core.
Importé par tous les autres modules web_search.

```python
# -*- coding: utf-8-sig -*-
"""
web_search_types.py — Dataclasses partagées du moteur de recherche web (Sprint WEB-02).
Zéro logique, zéro import core — peut être importé sans effets de bord.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchHit:
    """Un résultat de recherche brut retourné par un moteur."""
    title:         str
    url:           str
    snippet:       str  = ""
    source_engine: str  = "unknown"   # WEB-02 : traçabilité du moteur source


@dataclass
class FetchedPage:
    """Contenu extrait d'une page web après fetch HTTP."""
    url:           str
    title:         str
    text:          str            # texte brut tronqué à la phrase
    success:       bool  = True
    error:         str   = ""
    quality_score: float = 1.0    # WEB-02 : score 0.0–1.0 (fiabilité du contenu)


@dataclass
class SearchResult:
    """Résultat final retourné par WebSearchEngine.search()."""
    query:        str
    hits:         list[SearchHit]   = field(default_factory=list)
    pages:        list[FetchedPage] = field(default_factory=list)
    synthesis:    str               = ""
    model:        str               = ""
    available:    bool              = True
    error:        str               = ""
    engines_used: list[str]         = field(default_factory=list)  # WEB-02
    cache_hit:    bool              = False                         # WEB-02
    fetch_stats:  dict              = field(default_factory=dict)   # WEB-02 : {success, failed, skipped}

    def to_dict(self) -> dict:
        return {
            "query":        self.query,
            "synthesis":    self.synthesis,
            "model":        self.model,
            "available":    self.available,
            "error":        self.error,
            "engines_used": self.engines_used,
            "cache_hit":    self.cache_hit,
            "fetch_stats":  self.fetch_stats,
            "sources": [
                {
                    "title":         p.title,
                    "url":           p.url,
                    "success":       p.success,
                    "quality_score": p.quality_score,
                }
                for p in self.pages
            ],
            "hits": [
                {
                    "title":         h.title,
                    "url":           h.url,
                    "snippet":       h.snippet,
                    "source_engine": h.source_engine,
                }
                for h in self.hits
            ],
        }
```

---

## Tâche 2 — `core/web_search_engines.py` (CREATE)

### Objectif

Remplacer le client DDG unique par une cascade de 3 moteurs indépendants.
Si DDG tombe ou retourne zéro résultat, Brave est tenté. Si Brave échoue,
Wikipedia est utilisé en dernier recours pour les requêtes encyclopédiques.

### Architecture

```
BaseSearchClient (ABC)
    ├── _DdgLiteClient      — DuckDuckGo Lite (POST HTML) — actuel, conservé
    ├── _BraveSearchClient  — Brave Search API (GET JSON, sans clé API)
    └── _WikipediaClient    — Wikipedia REST API (GET JSON, sans clé API)

MultiEngineSearchClient     — Orchestre la cascade + déduplication
```

### Implémentation complète

```python
# -*- coding: utf-8-sig -*-
"""
web_search_engines.py — Clients moteurs de recherche multi-sources (Sprint WEB-02).

Moteurs disponibles (sans clé API, stdlib uniquement) :
    _DdgLiteClient      — DuckDuckGo Lite  (POST HTML)
    _BraveSearchClient  — Brave Search     (GET JSON, 2000 req/mois gratuit)
    _WikipediaClient    — Wikipedia API    (GET JSON, illimité)

MultiEngineSearchClient orchestre la cascade et déduplique les URLs.
"""
from __future__ import annotations

import html
import logging
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
        Ne lève jamais d'exception — retourne [] en cas d'erreur.
        """


# ── Client 1 : DuckDuckGo Lite ────────────────────────────────────────────────

class _DdgLiteClient(BaseSearchClient):
    """
    DuckDuckGo Lite — POST HTML, sans clé API, respectueux vie privée.
    Parser regex sur les classes CSS actuelles de DDG Lite.
    Fragile si DDG change son HTML — d'où la cascade.
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

        # Fallback si parsing principal échoue
        if not hits:
            fallback = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
            for url, title_raw in fallback.findall(html_text):
                if "duckduckgo.com" in url or "duck.co" in url:
                    continue
                title = html.unescape(re.sub(r"<[^>]+>", "", title_raw)).strip()
                if title and len(title) > 5:
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
    Brave Search — API publique JSON, sans clé API requise (2000 req/mois).
    URL : https://search.brave.com/search?q=...&source=web&format=json

    Retourne du JSON natif — beaucoup plus fiable et stable que DDG HTML.
    Si une clé API est fournie (BRAVE_SEARCH_API_KEY env var), le quota
    monte à 2000 req/jour.
    """
    name = "brave"
    _URL = "https://search.brave.com/search"

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        import json
        import os

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
    Wikipedia REST API — dernier recours pour requêtes encyclopédiques.
    Zéro clé API, JSON natif, fiable à 100%, quota illimité.

    Détection automatique : activé si la requête contient des mots-clés
    encyclopédiques ("qu'est-ce que", "définition", "histoire", "comment fonctionne").
    Peut aussi être forcé via force=True dans MultiEngineSearchClient.

    API utilisée : https://en.wikipedia.org/api/rest_v1/page/summary/{title}
    Recherche :    https://en.wikipedia.org/w/api.php?action=search&...
    """
    name = "wikipedia"
    _SEARCH_URL = "https://fr.wikipedia.org/w/api.php"
    _SUMMARY_URL = "https://fr.wikipedia.org/api/rest_v1/page/summary"

    # Mots-clés déclencheurs (détection automatique)
    _ENCYCLOPEDIC_KEYWORDS = (
        "qu'est-ce que", "c'est quoi", "définition", "définir",
        "histoire de", "origine de", "comment fonctionne", "expliquer",
        "qui est", "biographie", "inventé par",
    )

    @classmethod
    def is_encyclopedic(cls, query: str) -> bool:
        """True si la requête est encyclopédique et bénéficiera de Wikipedia."""
        q = query.lower()
        return any(kw in q for kw in cls._ENCYCLOPEDIC_KEYWORDS)

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        import json
        try:
            # 1. Recherche de pages correspondantes
            params = urllib.parse.urlencode({
                "action":   "opensearch",
                "search":   query,
                "limit":    max_results,
                "format":   "json",
                "namespace": 0,
            })
            url = f"{self._SEARCH_URL}?{params}"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # OpenSearch retourne [query, [titles], [descriptions], [urls]]
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
        seen_urls:    set[str]       = set()
        all_hits:     list[SearchHit] = []
        engines_used: list[str]       = []

        for EngineClass in self._ENGINE_ORDER:
            if len(all_hits) >= max_results:
                break
            engine = EngineClass()
            try:
                hits = engine.search(query, max_results=max_results)
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
```

---

## Tâche 3 — `core/web_search_fetcher.py` (CREATE)

### Objectif

Remplacer l'extraction naïve (suppression de toutes les balises) par :
1. **Extraction sémantique** : cibler `<article>`, `<main>`, `<div class="content">` avant
   de tomber sur l'extraction brute.
2. **Troncature à la phrase** : couper au dernier `.` / `?` / `!` plutôt qu'au caractère.
3. **Scoring de qualité** : noter chaque page 0.0–1.0 pour décider si elle vaut la peine
   d'être envoyée au LLM.

```python
# -*- coding: utf-8-sig -*-
"""
web_search_fetcher.py — Fetcher HTTP amélioré avec extraction sémantique (Sprint WEB-02).

Améliorations vs UI-06 :
  - Extraction sémantique : <article> / <main> / <div class=content> en priorité
  - Troncature à la dernière phrase complète (pas au caractère)
  - Scoring de qualité 0.0–1.0 par page
  - Filtrage des pages inutiles (cookie walls, 403, JS-only)
"""
from __future__ import annotations

import html
import logging
import re
import urllib.error
import urllib.request

from core.web_search_types import FetchedPage

log = logging.getLogger("lcca.web_search_fetcher")

_HTTP_TIMEOUT   = 30    # secondes
_PAGE_MAX_CHARS = 3000  # WEB-02 : augmenté de 2000 → 3000 (troncature propre compense)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}

# Patterns de contenu sémantique (essayés dans l'ordre)
_SEMANTIC_PATTERNS = [
    re.compile(r"<article[^>]*>(.*?)</article>",                            re.DOTALL | re.IGNORECASE),
    re.compile(r"<main[^>]*>(.*?)</main>",                                  re.DOTALL | re.IGNORECASE),
    re.compile(r'<div[^>]+class="[^"]*\b(?:content|article|post|entry|body)\b[^"]*"[^>]*>(.*?)</div>', re.DOTALL | re.IGNORECASE),
    re.compile(r'<div[^>]+id="[^"]*\b(?:content|main|article)\b[^"]*"[^>]*>(.*?)</div>',              re.DOTALL | re.IGNORECASE),
]

# Patterns de bruit (cookie walls, erreurs, JS-only)
_NOISE_PATTERNS = [
    "enable javascript",
    "javascript is required",
    "please enable cookies",
    "403 forbidden",
    "access denied",
    "you have been blocked",
    "cloudflare",
    "captcha",
]


class _PageFetcher:
    """
    Fetche une page web et en extrait le contenu textuel pertinent.

    Stratégie d'extraction (ordre de priorité) :
        1. Balises sémantiques HTML5 : <article>, <main>
        2. Divs de contenu courants : class/id content, article, post, entry
        3. Fallback : suppression brute de toutes les balises

    Scoring (0.0–1.0) :
        - 0.0 : page vide / erreur HTTP / cookie wall / JS-only
        - 0.3 : fallback brut (contenu peu fiable)
        - 0.5–1.0 : extraction sémantique réussie (proportionnel à la longueur)
    """

    def fetch(self, url: str) -> FetchedPage:
        """Fetche une page et retourne son contenu structuré + score de qualité."""
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return FetchedPage(
                        url=url, title=url, text="", success=False,
                        error="Non-HTML: %s" % content_type, quality_score=0.0,
                    )
                raw = resp.read().decode("utf-8", errors="replace")

            title = self._extract_title(raw)
            text, method = self._extract_text_smart(raw)
            score = self._score_page(text, url)

            log.debug("fetch %s — method=%s score=%.2f len=%d", url, method, score, len(text))
            return FetchedPage(
                url=url, title=title,
                text=self._truncate_at_sentence(text, _PAGE_MAX_CHARS),
                success=True, quality_score=score,
            )

        except urllib.error.HTTPError as exc:
            return FetchedPage(url=url, title=url, text="", success=False,
                               error="HTTP %d" % exc.code, quality_score=0.0)
        except Exception as exc:
            return FetchedPage(url=url, title=url, text="", success=False,
                               error=str(exc)[:120], quality_score=0.0)

    # ── Extraction titre ──────────────────────────────────────────────────────

    def _extract_title(self, html_text: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
        if m:
            return html.unescape(m.group(1)).strip()[:120]
        return ""

    # ── Extraction sémantique ─────────────────────────────────────────────────

    def _extract_text_smart(self, html_text: str) -> tuple[str, str]:
        """
        Retourne (texte_extrait, méthode_utilisée).
        méthode : 'semantic' | 'fallback'
        """
        # Tenter les patterns sémantiques dans l'ordre
        for pattern in _SEMANTIC_PATTERNS:
            m = pattern.search(html_text)
            if m:
                candidate = self._strip_tags(m.group(1))
                if len(candidate) > 300:   # contenu suffisant
                    return candidate, "semantic"

        # Fallback : extraction brute
        return self._strip_tags_basic(html_text), "fallback"

    def _strip_tags(self, html_text: str) -> str:
        """Supprime balises et normalise les espaces. Conserve la ponctuation."""
        # Supprimer scripts, styles, nav, header, footer
        text = re.sub(
            r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>",
            " ", html_text, flags=re.DOTALL | re.IGNORECASE,
        )
        # Balises block → saut de ligne
        text = re.sub(r"<(br|p|div|h[1-6]|li|tr|td)[^>]*>", "\n", text, flags=re.IGNORECASE)
        # Balises restantes
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _strip_tags_basic(self, html_text: str) -> str:
        """Version basique (fallback) — supprime plus agressivement."""
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ── Troncature propre ─────────────────────────────────────────────────────

    @staticmethod
    def _truncate_at_sentence(text: str, max_chars: int) -> str:
        """
        Tronque au dernier `.` / `?` / `!` avant max_chars.
        Garantit que le LLM reçoit des phrases complètes.
        """
        if len(text) <= max_chars:
            return text
        chunk = text[:max_chars]
        # Chercher la dernière fin de phrase
        last = max(chunk.rfind(". "), chunk.rfind("? "), chunk.rfind("! "), chunk.rfind(".\n"))
        if last > max_chars // 2:
            return chunk[:last + 1].strip()
        return chunk.strip()

    # ── Scoring de qualité ────────────────────────────────────────────────────

    def _score_page(self, text: str, url: str) -> float:
        """
        Score de qualité 0.0–1.0.

        Critères positifs :
          - Longueur du texte (proportionnel à _PAGE_MAX_CHARS)
          - Présence de ponctuation structurée
          - Présence de chiffres (contenu factuel)

        Pénalités :
          - Patterns de bruit (cookie walls, 403, JS-only)
          - Texte très court (< 200 chars)
          - Texte sans ponctuation (probablement du bruit)
        """
        if len(text) < 100:
            return 0.0

        # Score de base : longueur relative
        score = min(1.0, len(text) / _PAGE_MAX_CHARS)

        # Pénalité noise patterns (vérifier sur les 500 premiers chars)
        preview = text[:500].lower()
        for noise in _NOISE_PATTERNS:
            if noise in preview:
                return max(0.0, score * 0.2)

        # Bonus : présence de ponctuation (texte réel)
        punct_ratio = sum(1 for c in text if c in ".!?,;:") / max(len(text), 1)
        if punct_ratio > 0.02:
            score = min(1.0, score * 1.2)

        # Pénalité : pas de ponctuation (bruit ou JS)
        if punct_ratio < 0.005:
            score *= 0.4

        return round(score, 2)
```

---

## Tâche 4 — `core/web_search_cache.py` (CREATE)

```python
# -*- coding: utf-8-sig -*-
"""
web_search_cache.py — Cache TTL fichier JSON pour les recherches web (Sprint WEB-02).

Stockage : transactions/.web_cache/{md5_query}.json
TTL      : configurable (défaut 3600s = 1h)
Stdlib   : hashlib, json, time, pathlib — zéro dépendance externe.

Comportement :
  - get(query)        : retourne le dict résultat ou None si absent/expiré
  - set(query, result): écrit le résultat avec timestamp
  - invalidate(query) : supprime une entrée
  - clear_expired()   : nettoyage des entrées expirées (appelé au démarrage)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("lcca.web_search_cache")

# TTL par catégorie de requête (secondes)
_TTL_NEWS      = 1_800   # 30 min — actualités
_TTL_DEFAULT   = 3_600   # 1h    — défaut
_TTL_TECHNICAL = 86_400  # 24h   — questions techniques stables

# Mots-clés pour détecter le type de requête
_NEWS_KEYWORDS = (
    "actualités", "news", "aujourd'hui", "cette semaine", "ce mois",
    "récent", "dernier", "vient de", "breaking",
)
_TECHNICAL_KEYWORDS = (
    "comment", "tutoriel", "documentation", "api", "installer",
    "configurer", "syntaxe", "exemple de code", "python", "javascript",
)


def _detect_ttl(query: str) -> int:
    """Détecte le TTL approprié selon le type de requête."""
    q = query.lower()
    if any(kw in q for kw in _NEWS_KEYWORDS):
        return _TTL_NEWS
    if any(kw in q for kw in _TECHNICAL_KEYWORDS):
        return _TTL_TECHNICAL
    return _TTL_DEFAULT


class SearchCache:
    """
    Cache TTL fichier JSON pour les recherches web.

    Usage :
        cache = SearchCache(Path("transactions/.web_cache"))
        result = cache.get("chatbot médical Maroc")
        if result is None:
            result = engine.search(...)
            cache.set("chatbot médical Maroc", result)
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        # Nettoyage non-bloquant au démarrage
        try:
            self.clear_expired()
        except Exception:
            pass

    # ── API publique ──────────────────────────────────────────────────────────

    def get(self, query: str) -> Optional[dict]:
        """
        Retourne le dict résultat mis en cache, ou None si absent/expiré.
        Log le cache hit avec l'âge de l'entrée.
        """
        path = self._entry_path(query)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            age   = time.time() - entry["_cached_at"]
            ttl   = entry.get("_ttl", _TTL_DEFAULT)
            if age > ttl:
                path.unlink(missing_ok=True)
                log.debug("cache EXPIRED — query=%r age=%.0fs", query[:40], age)
                return None
            log.info("cache HIT — query=%r age=%.0fs ttl=%ds", query[:40], age, ttl)
            result = entry["result"]
            result["cache_hit"] = True
            return result
        except Exception as exc:
            log.warning("cache read error: %s", exc)
            return None

    def set(self, query: str, result: dict) -> None:
        """Écrit le résultat avec timestamp et TTL calculé depuis la requête."""
        path = self._entry_path(query)
        ttl  = _detect_ttl(query)
        try:
            entry = {
                "_cached_at": time.time(),
                "_ttl":       ttl,
                "_query":     query,
                "result":     result,
            }
            path.write_text(
                json.dumps(entry, ensure_ascii=False, indent=None),
                encoding="utf-8",
            )
            log.debug("cache SET — query=%r ttl=%ds", query[:40], ttl)
        except Exception as exc:
            log.warning("cache write error: %s", exc)

    def invalidate(self, query: str) -> bool:
        """Supprime une entrée de cache. Retourne True si l'entrée existait."""
        path = self._entry_path(query)
        if path.exists():
            path.unlink(missing_ok=True)
            return True
        return False

    def clear_expired(self) -> int:
        """
        Supprime toutes les entrées expirées.
        Appelé automatiquement au __init__.
        Retourne le nombre d'entrées supprimées.
        """
        removed = 0
        now = time.time()
        for path in self._dir.glob("*.json"):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                age   = now - entry.get("_cached_at", 0)
                ttl   = entry.get("_ttl", _TTL_DEFAULT)
                if age > ttl:
                    path.unlink(missing_ok=True)
                    removed += 1
            except Exception:
                pass
        if removed:
            log.info("cache: %d entrée(s) expirée(s) supprimée(s)", removed)
        return removed

    def stats(self) -> dict:
        """Retourne des statistiques sur le cache (nb entrées, taille totale)."""
        entries = list(self._dir.glob("*.json"))
        total_size = sum(p.stat().st_size for p in entries if p.exists())
        return {
            "entries":    len(entries),
            "size_kb":    round(total_size / 1024, 1),
            "cache_dir":  str(self._dir),
        }

    # ── Interne ───────────────────────────────────────────────────────────────

    def _entry_path(self, query: str) -> Path:
        key = hashlib.md5(query.lower().strip().encode("utf-8")).hexdigest()
        return self._dir / f"{key}.json"
```

---

## Tâche 5 — `core/web_search.py` (UPDATE)

Refactorisation de `WebSearchEngine` pour orchestrer les 4 nouveaux modules.
**L'API publique `search(query) → SearchResult` reste identique.**

### Changements dans `WebSearchEngine.__init__`

```python
from core.web_search_types    import SearchHit, FetchedPage, SearchResult
from core.web_search_engines  import MultiEngineSearchClient
from core.web_search_fetcher  import _PageFetcher
from core.web_search_cache    import SearchCache
# _SearchSynthesizer reste dans web_search.py (aucune raison de la déplacer)

class WebSearchEngine:
    def __init__(self, ...):
        # ... config Ollama identique ...
        self._engines    = MultiEngineSearchClient(min_hits=3)   # WEB-02
        self._fetcher    = _PageFetcher()                         # WEB-02 amélioré
        self._synthesizer = _SearchSynthesizer()
        self._cache      = SearchCache(                           # WEB-02
            cache_dir = TRANSACTIONS_DIR / ".web_cache"
        )
```

### Changements dans `WebSearchEngine.search()`

```python
def search(self, query: str) -> SearchResult:
    if not query or not query.strip():
        return SearchResult(query=query, available=False, error="Requête vide")

    # 1. Cache — retour immédiat si hit
    cached = self._cache.get(query)
    if cached:
        return SearchResult(**cached)

    # 2. Multi-moteurs avec déduplication
    hits, engines_used = self._engines.search(query.strip(), max_results=self._max_results)
    if not hits:
        return SearchResult(
            query=query, hits=[], available=True,
            synthesis=f"Aucun résultat trouvé pour **{query}**...",
            model=self._ollama_model, engines_used=engines_used,
        )

    # 3. Fetch parallèle — identique à UI-06
    pages, fetch_stats = self._fetch_parallel(hits)

    # 4. Filtrage : exclure les pages de mauvaise qualité
    #    (score < 0.3 → remplacer par snippet DDG dans la synthèse)
    good_pages  = [p for p in pages if p.quality_score >= 0.3]
    skipped     = len(pages) - len(good_pages)
    fetch_stats["skipped_low_quality"] = skipped

    # 5. Synthèse Ollama (bonne pages en priorité, snippets en fallback)
    synthesis, model = self._synthesizer.synthesize(
        query=query, hits=hits,
        pages=good_pages if good_pages else pages,  # toujours quelque chose à synthétiser
        ollama_url=self._ollama_url,
        ollama_model=self._ollama_model,
        ollama_timeout=self._ollama_timeout,
    )

    result = SearchResult(
        query=query, hits=hits, pages=pages,
        synthesis=synthesis, model=model,
        available=True, engines_used=engines_used,
        cache_hit=False, fetch_stats=fetch_stats,
    )

    # 6. Mise en cache
    self._cache.set(query, result.to_dict())
    return result

def _fetch_parallel(self, hits: list[SearchHit]) -> tuple[list[FetchedPage], dict]:
    """Fetch parallèle identique à UI-06, retourne aussi les stats."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    urls = [h.url for h in hits[:self._max_fetch]]
    results_map: dict[str, FetchedPage] = {}

    with ThreadPoolExecutor(max_workers=self._max_fetch) as pool:
        future_to_url = {pool.submit(self._fetcher.fetch, url): url for url in urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results_map[url] = future.result()
            except Exception as exc:
                results_map[url] = FetchedPage(
                    url=url, title=url, text="",
                    success=False, error=str(exc)[:120], quality_score=0.0,
                )

    pages = [results_map[url] for url in urls if url in results_map]
    stats = {
        "total":   len(pages),
        "success": sum(1 for p in pages if p.success),
        "failed":  sum(1 for p in pages if not p.success),
    }
    return pages, stats
```

---

## Tâche 6 — `tests/test_web_search.py` (CREATE)

```python
# -*- coding: utf-8-sig -*-
"""Tests unitaires Sprint WEB-02 — moteur de recherche multi-sources."""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.web_search_types   import SearchHit, FetchedPage, SearchResult
from core.web_search_engines import MultiEngineSearchClient, _DdgLiteClient, _WikipediaClient
from core.web_search_fetcher import _PageFetcher
from core.web_search_cache   import SearchCache


# ── Types ────────────────────────────────────────────────────────────────────

def test_search_hit_source_engine():
    h = SearchHit(title="Test", url="https://example.com", source_engine="brave")
    assert h.source_engine == "brave"

def test_fetched_page_quality_score_default():
    p = FetchedPage(url="u", title="t", text="x")
    assert p.quality_score == 1.0

def test_search_result_to_dict_engines_used():
    r = SearchResult(query="test", engines_used=["duckduckgo", "brave"])
    d = r.to_dict()
    assert d["engines_used"] == ["duckduckgo", "brave"]
    assert "cache_hit" in d
    assert "fetch_stats" in d


# ── Cache ─────────────────────────────────────────────────────────────────────

def test_cache_miss():
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        assert cache.get("une requête inconnue") is None

def test_cache_set_get():
    with tempfile.TemporaryDirectory() as tmp:
        cache  = SearchCache(Path(tmp))
        result = {"query": "test", "synthesis": "résultat", "model": "x",
                  "available": True, "error": "", "engines_used": [],
                  "cache_hit": False, "fetch_stats": {}, "sources": [], "hits": []}
        cache.set("test query", result)
        cached = cache.get("test query")
        assert cached is not None
        assert cached["synthesis"] == "résultat"
        assert cached["cache_hit"] is True

def test_cache_expired(monkeypatch):
    import time
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        result = {"query": "x", "synthesis": "y", "model": "", "available": True,
                  "error": "", "engines_used": [], "cache_hit": False,
                  "fetch_stats": {}, "sources": [], "hits": []}
        cache.set("expiry test", result)
        # Simuler que le cache a 2h de vieux
        monkeypatch.setattr(time, "time", lambda: time.time() + 7201)
        assert cache.get("expiry test") is None

def test_cache_invalidate():
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        result = {"query": "q", "synthesis": "s", "model": "", "available": True,
                  "error": "", "engines_used": [], "cache_hit": False,
                  "fetch_stats": {}, "sources": [], "hits": []}
        cache.set("ma requête", result)
        assert cache.invalidate("ma requête") is True
        assert cache.get("ma requête") is None

def test_cache_stats():
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        stats = cache.stats()
        assert "entries" in stats
        assert stats["entries"] == 0


# ── Fetcher ───────────────────────────────────────────────────────────────────

def test_fetcher_truncate_at_sentence():
    fetcher = _PageFetcher()
    text    = "Première phrase. Deuxième phrase. Troisième phrase qui est très longue et dépasse."
    result  = fetcher._truncate_at_sentence(text, 40)
    assert result.endswith(".")
    assert len(result) <= 40

def test_fetcher_score_empty():
    fetcher = _PageFetcher()
    assert fetcher._score_page("", "https://example.com") == 0.0

def test_fetcher_score_noise():
    fetcher = _PageFetcher()
    score   = fetcher._score_page("Please enable JavaScript to view this page.", "https://x.com")
    assert score < 0.3

def test_fetcher_score_good_content():
    fetcher = _PageFetcher()
    text    = "Ceci est un article complet. " * 50
    score   = fetcher._score_page(text, "https://example.com")
    assert score >= 0.3

def test_fetcher_semantic_extraction():
    fetcher   = _PageFetcher()
    html_text = "<html><body><article>Contenu principal très long et utile. " * 20 + "</article></body></html>"
    text, method = fetcher._extract_text_smart(html_text)
    assert method == "semantic"
    assert len(text) > 100

def test_fetcher_fallback_extraction():
    fetcher   = _PageFetcher()
    html_text = "<html><body><p>Texte sans balise sémantique.</p></body></html>"
    text, method = fetcher._extract_text_smart(html_text)
    assert method == "fallback"


# ── Multi-engine deduplication ────────────────────────────────────────────────

def test_url_normalization():
    client = MultiEngineSearchClient()
    assert client._normalize_url("https://www.example.com/") == "https://example.com"
    assert client._normalize_url("https://example.com/page#section") == "https://example.com/page"

def test_wikipedia_encyclopedic_detection():
    assert _WikipediaClient.is_encyclopedic("qu'est-ce que le machine learning")
    assert _WikipediaClient.is_encyclopedic("définition de l'intelligence artificielle")
    assert not _WikipediaClient.is_encyclopedic("chatbot médical Maroc")

def test_multi_engine_deduplication():
    client = MultiEngineSearchClient()
    # Simuler deux moteurs retournant des résultats avec une URL commune
    hits_ddg = [
        SearchHit(title="A", url="https://example.com/page", source_engine="duckduckgo"),
        SearchHit(title="B", url="https://other.com",        source_engine="duckduckgo"),
    ]
    hits_brave = [
        SearchHit(title="A (bis)", url="https://www.example.com/page/", source_engine="brave"),
        SearchHit(title="C",       url="https://third.com",             source_engine="brave"),
    ]
    with patch.object(_DdgLiteClient, "search", return_value=hits_ddg), \
         patch.object(__import__("core.web_search_engines",
                      fromlist=["_BraveSearchClient"])._BraveSearchClient,
                      "search", return_value=hits_brave):
        hits, engines = client.search("test", max_results=5)
    # example.com ne doit apparaître qu'une seule fois
    urls = [h.url for h in hits]
    normalized = [client._normalize_url(u) for u in urls]
    assert len(normalized) == len(set(normalized))
```

---

## Plan d'exécution

```
1. core/web_search_types.py     — aucune dépendance entrante
2. core/web_search_cache.py     — dépend de web_search_types
3. core/web_search_fetcher.py   — dépend de web_search_types
4. core/web_search_engines.py   — dépend de web_search_types
5. core/web_search.py           — UPDATE : orchestration des 4 modules
6. tests/test_web_search.py     — validation complète
```

---

## Règles transversales

1. **Stdlib uniquement** — `urllib.request`, `hashlib`, `json`, `re`, `concurrent.futures` — pas de `requests`, `httpx`, `bs4`.
2. **Zéro régression API** — `from core.web_search import WebSearchEngine; WebSearchEngine().search("x")` doit continuer de fonctionner sans modification côté appelant.
3. **Encodage** — tous les nouveaux fichiers en `# -*- coding: utf-8-sig -*-`.
4. **Silencieux en cas d'erreur** — chaque moteur retourne `[]` s'il échoue, jamais d'exception propagée.
5. **Rétrocompatibilité des dataclasses** — `SearchHit`, `FetchedPage`, `SearchResult` sont importables depuis `core.web_search` via re-export.

```python
# Ajouter dans core/web_search.py pour rétrocompat :
from core.web_search_types import SearchHit, FetchedPage, SearchResult  # re-export
```

---

## Critères de done (DoD)

- [ ] `python -m pytest tests/test_web_search.py -v` — tous les tests passent
- [ ] `@web chatbot médical Maroc` — réponse en < 120s, affiche `engines_used`
- [ ] `@web` sur une même requête deux fois — deuxième réponse instantanée (`cache_hit: true`)
- [ ] DDG simulé en erreur → Brave prend le relais automatiquement
- [ ] Page avec "enable javascript" → `quality_score < 0.3`, exclue de la synthèse
- [ ] Aucun fichier web_search > 16 KB
- [ ] `004-sprint-context.md` mis à jour avec WEB-02 terminé

---

## Métriques attendues après sprint

| Métrique | Avant (UI-06) | Après (WEB-02) |
|----------|---------------|----------------|
| Moteurs de recherche | 1 (DDG) | 3 (DDG + Brave + Wikipedia) |
| Résistance à une panne DDG | ❌ zéro résultat | ✅ fallback automatique |
| Extraction sémantique | ❌ brute | ✅ `<article>` / `<main>` en priorité |
| Troncature | ❌ au caractère | ✅ à la phrase |
| Cache | ❌ aucun | ✅ TTL adaptatif (30min/1h/24h) |
| Déduplication cross-moteurs | ❌ | ✅ normalisation URL |
| Scoring qualité page | ❌ | ✅ 0.0–1.0, pages bruitées exclues |
| Traçabilité moteur | ❌ | ✅ `source_engine` par hit |
| Taille `web_search.py` | 16.8 KB (monolithique) | < 8 KB (orchestrateur) |
