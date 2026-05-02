# -*- coding: utf-8-sig -*-
"""web_search.py — WebSearchEngine orchestrateur (Sprint WEB-02).

Moteur de recherche web intégré à LCCA.
Refactorisé en orchestrateur léger — les composants sont dans des modules dédiés :
    core/web_search_types.py    — Dataclasses SearchHit, FetchedPage, SearchResult
    core/web_search_engines.py  — MultiEngineSearchClient (DDG + Brave + Wikipedia)
    core/web_search_fetcher.py  — _PageFetcher avec extraction sémantique + scoring
    core/web_search_cache.py    — SearchCache TTL adaptatif

Architecture :
    WebSearchEngine              — Interface publique (inchangée)
    _SearchSynthesizer           — Synthèse via OllamaClient (conservée ici)

Flux :
    search(query)
      → cache hit?             → retour immédiat
      → MultiEngineSearchClient → DDG + Brave + Wikipedia (cascade + déduplication)
      → _PageFetcher            → fetch parallèle + scoring qualité
      → filtrage pages (score < 0.3 → exclues de synthèse)
      → _SearchSynthesizer      → synthèse Ollama
      → SearchCache.set()       → mise en cache

Contraintes LCCA :
    - urllib.request stdlib uniquement (pas de requests)
    - Timeout 30s par requête HTTP fetch, 15s par moteur de recherche
    - Fetch des pages EN PARALLÈLE (ThreadPoolExecutor)
    - Troncature à la phrase (pas au caractère) — 3000 chars/page max
    - Synthèse Ollama obligatoire — jamais retourner du HTML brut

Budget temps total attendu (WEB-02) :
    fetch 3 pages (parallèle, max 30s)     ≈ 30s
    synthèse Ollama (llama3.2:3b CPU)      ≈ 60–90s
    total                                  ≈ 90–120s (sous le timeout UI 240s)

API publique (inchangée depuis UI-06) :
    from core.web_search import WebSearchEngine, SearchHit, FetchedPage, SearchResult
    engine = WebSearchEngine()
    result = engine.search("chatbot médical Maroc")
    print(result.synthesis)
    print(result.to_dict())
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# Re-exports rétrocompat — importables depuis core.web_search comme avant UI-06
from core.web_search_types   import SearchHit, FetchedPage, SearchResult  # noqa: F401
from core.web_search_engines import MultiEngineSearchClient
from core.web_search_fetcher import _PageFetcher
from core.web_search_cache   import SearchCache

log = logging.getLogger("lcca.web_search")

# ── Constantes ────────────────────────────────────────────────────────────────
_MAX_RESULTS = 5      # résultats moteurs à récupérer
_MAX_FETCH   = 3      # pages à fetcher parmi les résultats
_MIN_QUALITY = 0.3    # score qualité minimum pour inclure dans synthèse

_SYNTHESIS_SYSTEM = """\
Tu es un assistant de recherche. On te fournit une question et des extraits de pages web.
Synthétise une réponse claire et factuelle en français.
Règles :
- Cite les sources (URL) entre crochets après chaque information clé : [source 1], [source 2]…
- Si les sources sont contradictoires, mentionne-le explicitement.
- Si les extraits sont insuffisants, dis-le.
- Réponds en Markdown structuré (titres ## si nécessaire, listes -).
- Maximum 400 mots.
"""

_PAGE_MAX_CHARS = 3000  # pour la synthèse (aligné avec web_search_fetcher)


# ── Synthesizer ───────────────────────────────────────────────────────────────

class _SearchSynthesizer:
    """Synthétise les pages fetchées en réponse via OllamaClient."""

    def synthesize(
        self,
        query:         str,
        hits:          list[SearchHit],
        pages:         list[FetchedPage],
        ollama_url:    str,
        ollama_model:  str,
        ollama_timeout: int,
    ) -> tuple[str, str]:
        """
        Retourne (synthesis_text, model_used).
        Si Ollama indisponible, retourne un résumé des snippets.
        """
        from core.llm_generator import OllamaClient
        client = OllamaClient(
            base_url   = ollama_url,
            model      = ollama_model,
            timeout    = ollama_timeout,
            max_tokens = 600,
        )

        # Construire le contexte pour le LLM
        context_parts = [f"**Question** : {query}\n"]
        for i, page in enumerate(pages, 1):
            if page.success and page.text:
                context_parts.append(
                    f"**Source {i}** — [{page.title}]({page.url})\n{page.text[:_PAGE_MAX_CHARS]}"
                )
            elif hits and i <= len(hits):
                hit = hits[i - 1]
                context_parts.append(
                    f"**Source {i}** — [{hit.title}]({hit.url})\n{hit.snippet}"
                )

        user_prompt = "\n\n---\n\n".join(context_parts)

        if not client.is_available():
            log.warning("Ollama unavailable — returning snippet-only summary")
            return self._fallback_summary(query, hits, pages), ollama_model

        try:
            synthesis = client.generate(system=_SYNTHESIS_SYSTEM, user=user_prompt)
            return synthesis if isinstance(synthesis, str) else str(synthesis), ollama_model
        except Exception as exc:
            log.warning("Ollama synthesis failed: %s", exc)
            return self._fallback_summary(query, hits, pages), ollama_model

    def _fallback_summary(
        self,
        query: str,
        hits:  list[SearchHit],
        pages: list[FetchedPage],
    ) -> str:
        """Résumé de fallback sans LLM — snippets DDG uniquement."""
        lines = [f"## Résultats pour : {query}\n"]
        for i, hit in enumerate(hits[:_MAX_RESULTS], 1):
            lines.append(f"**{i}. [{hit.title}]({hit.url})**")
            if hit.snippet:
                lines.append(f"> {hit.snippet}")
            lines.append("")
        return "\n".join(lines)


# ── Interface publique ────────────────────────────────────────────────────────

class WebSearchEngine:
    """
    Interface publique du moteur de recherche web LCCA.

    Usage :
        engine = WebSearchEngine()
        result = engine.search("chatbot médical Maroc")
        print(result.synthesis)   # texte synthétisé
        print(result.to_dict())   # dict sérialisable JSON

    API inchangée depuis UI-06 — zéro régression pour les appelants.
    """

    def __init__(
        self,
        ollama_url:     Optional[str] = None,
        ollama_model:   Optional[str] = None,
        ollama_timeout: Optional[int] = None,
        max_results:    int           = _MAX_RESULTS,
        max_fetch:      int           = _MAX_FETCH,
    ) -> None:
        try:
            import config
            self._ollama_url     = ollama_url     or config.OLLAMA_URL
            self._ollama_model   = ollama_model   or config.OLLAMA_MODEL
            self._ollama_timeout = ollama_timeout or config.OLLAMA_TIMEOUT
            _cache_dir = getattr(config, "WEB_CACHE_DIR", config.TRANSACTIONS_DIR / ".web_cache")
        except (ImportError, AttributeError):
            import pathlib
            self._ollama_url     = ollama_url     or "http://localhost:11434"
            self._ollama_model   = ollama_model   or "llama3.2:3b"
            self._ollama_timeout = ollama_timeout or 90
            _cache_dir = pathlib.Path("transactions") / ".web_cache"

        self._max_results  = max_results
        self._max_fetch    = max_fetch
        self._engines      = MultiEngineSearchClient(min_hits=3)   # WEB-02
        self._fetcher      = _PageFetcher()                         # WEB-02 amélioré
        self._synthesizer  = _SearchSynthesizer()
        self._cache        = SearchCache(cache_dir=_cache_dir)      # WEB-02

    def search(self, query: str) -> SearchResult:
        """
        Effectue une recherche complète :
          1. Cache — retour immédiat si hit
          2. Multi-moteurs (DDG + Brave + Wikipedia) avec déduplication
          3. Fetch parallèle des top N pages avec scoring qualité
          4. Filtrage : pages qualité < 0.3 exclues de la synthèse
          5. Synthèse Ollama
          6. Mise en cache du résultat

        Retourne toujours un SearchResult (jamais de levée d'exception).
        """
        if not query or not query.strip():
            return SearchResult(
                query     = query,
                available = False,
                error     = "Requête vide",
            )

        log.info("web_search: query=%r", query)

        # 1. Cache hit
        cached = self._cache.get(query)
        if cached:
            log.info("web_search: cache hit pour query=%r", query)
            return SearchResult(**{k: v for k, v in cached.items()
                                   if k in SearchResult.__dataclass_fields__})

        # 2. Multi-moteurs avec déduplication
        hits, engines_used = self._engines.search(query.strip(), max_results=self._max_results)
        if not hits:
            log.warning("web_search: aucun résultat pour %r", query)
            return SearchResult(
                query        = query,
                hits         = [],
                available    = True,
                synthesis    = (
                    f"Aucun résultat trouvé pour **{query}**.\n\n"
                    "Essayez de reformuler la recherche ou vérifiez la connexion internet."
                ),
                model        = self._ollama_model,
                engines_used = engines_used,
            )

        # 3. Fetch parallèle
        pages, fetch_stats = self._fetch_parallel(hits)

        # 4. Filtrage qualité + ranking post-fetch (WEB-03)
        # Trier pages par quality_score décroissant : les meilleures sources
        # en premier → la synthèse Ollama voit les extraits les plus riables.
        pages_ranked = sorted(pages, key=lambda p: p.quality_score, reverse=True)
        good_pages   = [p for p in pages_ranked if p.quality_score >= _MIN_QUALITY]
        skipped      = len(pages) - len(good_pages)
        fetch_stats["skipped_low_quality"] = skipped
        if skipped:
            log.info("web_search: %d page(s) exclues (qualité < %.1f)", skipped, _MIN_QUALITY)
        # Même ranking sur les hits : aligner l'ordre hits ↔ pages pour la synthèse
        url_to_score = {p.url: p.quality_score for p in pages}
        hits_ranked  = sorted(hits, key=lambda h: url_to_score.get(h.url, 0.0), reverse=True)

        # 5. Synthèse Ollama
        synthesis, model = self._synthesizer.synthesize(
            query          = query,
            hits           = hits_ranked,
            pages          = good_pages if good_pages else pages_ranked,
            ollama_url     = self._ollama_url,
            ollama_model   = self._ollama_model,
            ollama_timeout = self._ollama_timeout,
        )

        result = SearchResult(
            query        = query,
            hits         = hits,
            pages        = pages,
            synthesis    = synthesis,
            model        = model,
            available    = True,
            engines_used = engines_used,
            cache_hit    = False,
            fetch_stats  = fetch_stats,
        )

        # 6. Mise en cache
        self._cache.set(query, result.to_dict())
        return result

    def _fetch_parallel(
        self,
        hits: list[SearchHit],
    ) -> tuple[list[FetchedPage], dict]:
        """Fetch parallèle des pages. Retourne (pages, stats)."""
        urls_to_fetch = [h.url for h in hits[:self._max_fetch]]
        results_map: dict[str, FetchedPage] = {}

        with ThreadPoolExecutor(max_workers=self._max_fetch) as pool:
            future_to_url = {
                pool.submit(self._fetcher.fetch, url): url
                for url in urls_to_fetch
            }
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    results_map[url] = future.result()
                except Exception as exc:
                    from core.web_search_types import FetchedPage as _FP
                    results_map[url] = _FP(
                        url=url, title=url, text="",
                        success=False, error=str(exc)[:120], quality_score=0.0,
                    )

        # Respecter l'ordre original des hits
        pages = [results_map[url] for url in urls_to_fetch if url in results_map]
        for p in pages:
            log.debug("web_search: fetch %s — success=%s score=%.2f", p.url, p.success, p.quality_score)

        stats = {
            "total":   len(pages),
            "success": sum(1 for p in pages if p.success),
            "failed":  sum(1 for p in pages if not p.success),
        }
        return pages, stats
