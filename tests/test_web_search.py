# -*- coding: utf-8-sig -*-
"""Tests unitaires Sprint WEB-02/WEB-03 — moteur de recherche multi-sources."""
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.web_search_types   import SearchHit, FetchedPage, SearchResult
from core.web_search_engines import MultiEngineSearchClient, _DdgLiteClient, _WikipediaClient, _BraveSearchClient
from core.web_search_fetcher import _PageFetcher
from core.web_search_cache   import SearchCache


# ── Types ────────────────────────────────────────────────────────────────────

def test_search_hit_source_engine():
    h = SearchHit(title="Test", url="https://example.com", source_engine="brave")
    assert h.source_engine == "brave"

def test_search_hit_default_source_engine():
    h = SearchHit(title="Test", url="https://example.com")
    assert h.source_engine == "unknown"

def test_fetched_page_quality_score_default():
    p = FetchedPage(url="u", title="t", text="x")
    assert p.quality_score == 1.0

def test_search_result_to_dict_engines_used():
    r = SearchResult(query="test", engines_used=["duckduckgo", "brave"])
    d = r.to_dict()
    assert d["engines_used"] == ["duckduckgo", "brave"]
    assert "cache_hit" in d
    assert "fetch_stats" in d

def test_search_result_to_dict_quality_score_in_sources():
    p = FetchedPage(url="https://x.com", title="X", text="bla", quality_score=0.75)
    r = SearchResult(query="test", pages=[p])
    d = r.to_dict()
    assert d["sources"][0]["quality_score"] == 0.75

def test_search_result_to_dict_source_engine_in_hits():
    h = SearchHit(title="A", url="https://a.com", source_engine="wikipedia")
    r = SearchResult(query="test", hits=[h])
    d = r.to_dict()
    assert d["hits"][0]["source_engine"] == "wikipedia"


# ── Cache ─────────────────────────────────────────────────────────────────────

def test_cache_miss():
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        assert cache.get("une requête inconnue") is None

def test_cache_set_get():
    with tempfile.TemporaryDirectory() as tmp:
        cache  = SearchCache(Path(tmp))
        result = {
            "query": "test", "synthesis": "résultat", "model": "x",
            "available": True, "error": "", "engines_used": [],
            "cache_hit": False, "fetch_stats": {}, "sources": [], "hits": [],
        }
        cache.set("test query", result)
        cached = cache.get("test query")
        assert cached is not None
        assert cached["synthesis"] == "résultat"
        assert cached["cache_hit"] is True

def test_cache_expired(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        result = {
            "query": "x", "synthesis": "y", "model": "", "available": True,
            "error": "", "engines_used": [], "cache_hit": False,
            "fetch_stats": {}, "sources": [], "hits": [],
        }
        cache.set("expiry test", result)
        # Simuler que le temps a avancé de 2h+
        original_time = time.time()
        monkeypatch.setattr("core.web_search_cache.time.time", lambda: original_time + 7201)
        assert cache.get("expiry test") is None

def test_cache_invalidate():
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        result = {
            "query": "q", "synthesis": "s", "model": "", "available": True,
            "error": "", "engines_used": [], "cache_hit": False,
            "fetch_stats": {}, "sources": [], "hits": [],
        }
        cache.set("ma requête", result)
        assert cache.invalidate("ma requête") is True
        assert cache.get("ma requête") is None

def test_cache_invalidate_nonexistent():
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        assert cache.invalidate("inexistant") is False

def test_cache_stats_empty():
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        stats = cache.stats()
        assert "entries" in stats
        assert stats["entries"] == 0

def test_cache_stats_after_set():
    with tempfile.TemporaryDirectory() as tmp:
        cache = SearchCache(Path(tmp))
        result = {
            "query": "q", "synthesis": "s", "model": "", "available": True,
            "error": "", "engines_used": [], "cache_hit": False,
            "fetch_stats": {}, "sources": [], "hits": [],
        }
        cache.set("requête stats", result)
        stats = cache.stats()
        assert stats["entries"] == 1
        assert stats["size_kb"] > 0

def test_cache_ttl_news():
    """Les requêtes d'actualités ont un TTL court (30min)."""
    from core.web_search_cache import _detect_ttl, _TTL_NEWS
    assert _detect_ttl("actualités technologie aujourd'hui") == _TTL_NEWS

def test_cache_ttl_technical():
    """Les requêtes techniques ont un TTL long (24h)."""
    from core.web_search_cache import _detect_ttl, _TTL_TECHNICAL
    assert _detect_ttl("comment installer python") == _TTL_TECHNICAL


# ── Fetcher ───────────────────────────────────────────────────────────────────

def test_fetcher_truncate_at_sentence_short():
    fetcher = _PageFetcher()
    text    = "Phrase courte."
    assert fetcher._truncate_at_sentence(text, 100) == text

def test_fetcher_truncate_at_sentence_long():
    fetcher = _PageFetcher()
    text    = "Première phrase. Deuxième phrase. Troisième phrase qui est très longue et dépasse."
    result  = fetcher._truncate_at_sentence(text, 40)
    assert result.endswith(".")
    assert len(result) <= 40

def test_fetcher_score_empty():
    fetcher = _PageFetcher()
    assert fetcher._score_page("", "https://example.com") == 0.0

def test_fetcher_score_very_short():
    fetcher = _PageFetcher()
    assert fetcher._score_page("ok", "https://example.com") == 0.0

def test_fetcher_score_noise():
    fetcher = _PageFetcher()
    score   = fetcher._score_page("Please enable JavaScript to view this page. Some more text here.", "https://x.com")
    assert score < 0.3

def test_fetcher_score_good_content():
    fetcher = _PageFetcher()
    text    = "Ceci est un article complet avec du contenu. Il contient plusieurs phrases. " * 30
    score   = fetcher._score_page(text, "https://example.com")
    assert score >= 0.3

def test_fetcher_semantic_extraction():
    fetcher   = _PageFetcher()
    html_text = "<html><body><article>" + ("Contenu principal très long et utile. " * 20) + "</article></body></html>"
    text, method = fetcher._extract_text_smart(html_text)
    assert method == "semantic"
    assert len(text) > 100

def test_fetcher_fallback_extraction():
    fetcher   = _PageFetcher()
    html_text = "<html><body><p>Texte sans balise sémantique.</p></body></html>"
    _text, method = fetcher._extract_text_smart(html_text)
    assert method == "fallback"

def test_fetcher_semantic_extraction_main():
    fetcher   = _PageFetcher()
    html_text = "<html><body><main>" + ("Contenu principal dans main. " * 20) + "</main></body></html>"
    text, method = fetcher._extract_text_smart(html_text)
    assert method == "semantic"

def test_fetcher_extract_title():
    fetcher   = _PageFetcher()
    html_text = "<html><head><title>Mon titre de page</title></head><body></body></html>"
    assert fetcher._extract_title(html_text) == "Mon titre de page"


# ── Multi-engine deduplication ────────────────────────────────────────────────

def test_url_normalization_www():
    client = MultiEngineSearchClient()
    assert client._normalize_url("https://www.example.com/") == "https://example.com"

def test_url_normalization_fragment():
    client = MultiEngineSearchClient()
    assert client._normalize_url("https://example.com/page#section") == "https://example.com/page"

def test_url_normalization_trailing_slash():
    client = MultiEngineSearchClient()
    assert client._normalize_url("https://example.com/page/") == "https://example.com/page"

def test_wikipedia_encyclopedic_detection_true():
    assert _WikipediaClient.is_encyclopedic("qu'est-ce que le machine learning")
    assert _WikipediaClient.is_encyclopedic("définition de l'intelligence artificielle")
    assert _WikipediaClient.is_encyclopedic("histoire de la photographie")

def test_wikipedia_encyclopedic_detection_false():
    assert not _WikipediaClient.is_encyclopedic("chatbot médical Maroc")
    assert not _WikipediaClient.is_encyclopedic("meilleur restaurant Paris")

def test_multi_engine_deduplication():
    """Une même URL normalisée ne doit apparaître qu'une seule fois."""
    client = MultiEngineSearchClient()
    hits_ddg = [
        SearchHit(title="A", url="https://example.com/page",  source_engine="duckduckgo"),
        SearchHit(title="B", url="https://other.com",          source_engine="duckduckgo"),
    ]
    hits_brave = [
        SearchHit(title="A (bis)", url="https://www.example.com/page/", source_engine="brave"),
        SearchHit(title="C",       url="https://third.com",             source_engine="brave"),
    ]
    with patch.object(_DdgLiteClient,      "search", return_value=hits_ddg), \
         patch.object(_BraveSearchClient,  "search", return_value=hits_brave), \
         patch.object(_WikipediaClient,    "search", return_value=[]):
        hits, engines = client.search("test", max_results=5)

    # example.com ne doit apparaître qu'une seule fois
    normalized = [client._normalize_url(h.url) for h in hits]
    assert len(normalized) == len(set(normalized))

def test_multi_engine_engines_used():
    """engines_used doit lister les moteurs qui ont retourné des résultats."""
    client = MultiEngineSearchClient()
    hits_ddg = [SearchHit(title="A", url="https://a.com", source_engine="duckduckgo")]
    with patch.object(_DdgLiteClient,     "search", return_value=hits_ddg), \
         patch.object(_BraveSearchClient, "search", return_value=[]), \
         patch.object(_WikipediaClient,   "search", return_value=[]):
        _hits, engines = client.search("test", max_results=5)
    assert "duckduckgo" in engines
    assert "brave" not in engines

def test_multi_engine_fallback_to_wikipedia_when_encyclopedic():
    """Wikipedia est toujours tenté pour les requêtes encyclopédiques."""
    client   = MultiEngineSearchClient()
    wiki_hit = SearchHit(title="W", url="https://fr.wikipedia.org/wiki/IA", source_engine="wikipedia")
    with patch.object(_DdgLiteClient,     "search", return_value=[]), \
         patch.object(_BraveSearchClient, "search", return_value=[]), \
         patch.object(_WikipediaClient,   "search", return_value=[wiki_hit]):
        hits, engines = client.search("qu'est-ce que l'intelligence artificielle", max_results=5)
    assert any(h.source_engine == "wikipedia" for h in hits)
    assert "wikipedia" in engines


# ── WEB-03 : Ranking post-fetch ────────────────────────────────────────────

def test_ranking_best_page_first():
    """
    WEB-03 — Après fetch, les pages de meilleure qualité sont soumises
    en premier au synthétiseur.
    """
    from core.web_search import WebSearchEngine

    hits = [
        SearchHit(title="Good",    url="https://good.com",   source_engine="duckduckgo"),
        SearchHit(title="Bad",     url="https://bad.com",    source_engine="duckduckgo"),
        SearchHit(title="Medium",  url="https://medium.com", source_engine="duckduckgo"),
    ]
    pages = [
        FetchedPage(url="https://good.com",   title="G", text="Bon contenu.", success=True,  quality_score=0.9),
        FetchedPage(url="https://bad.com",    title="B", text="",             success=False, quality_score=0.0),
        FetchedPage(url="https://medium.com", title="M", text="Moyen.",       success=True,  quality_score=0.5),
    ]
    received_pages = []

    def _mock_synthesize(query, hits, pages, **kwargs):
        received_pages.extend(pages)
        return "synthèse", "model"

    engine = WebSearchEngine()
    engine._synthesizer.synthesize = _mock_synthesize

    with patch.object(engine._engines, "search", return_value=(hits, ["duckduckgo"])), \
         patch.object(engine._fetcher, "fetch", side_effect=lambda url: next(
             p for p in pages if p.url == url
         )), \
         patch.object(engine._cache, "get", return_value=None), \
         patch.object(engine._cache, "set", return_value=None):
        engine.search("test ranking")

    # La page "Good" (score 0.9) doit être la première soumise au synthétiseur
    assert received_pages[0].url == "https://good.com"


def test_ranking_excludes_low_quality_pages():
    """
    WEB-03 — Les pages avec quality_score < 0.3 sont exclues de la synthèse
    et comptabilisées dans fetch_stats["skipped_low_quality"].
    """
    from core.web_search import WebSearchEngine

    hits = [
        SearchHit(title="A", url="https://a.com", source_engine="duckduckgo"),
        SearchHit(title="B", url="https://b.com", source_engine="duckduckgo"),
    ]
    pages = [
        FetchedPage(url="https://a.com", title="A", text="Contenu A.", success=True,  quality_score=0.8),
        FetchedPage(url="https://b.com", title="B", text="JS only.",   success=True,  quality_score=0.1),
    ]
    received_pages = []

    def _mock_synthesize(query, hits, pages, **kwargs):
        received_pages.extend(pages)
        return "synthèse", "model"

    engine = WebSearchEngine()
    engine._synthesizer.synthesize = _mock_synthesize

    with patch.object(engine._engines, "search", return_value=(hits, ["duckduckgo"])), \
         patch.object(engine._fetcher, "fetch", side_effect=lambda url: next(
             p for p in pages if p.url == url
         )), \
         patch.object(engine._cache, "get", return_value=None), \
         patch.object(engine._cache, "set", return_value=None):
        result = engine.search("test exclusion qualité")

    # Seule la page A (score 0.8 >= 0.3) doit être soumise
    assert len(received_pages) == 1
    assert received_pages[0].url == "https://a.com"
    # fetch_stats doit reporter le skip
    assert result.fetch_stats.get("skipped_low_quality", 0) == 1


# ── WEB-03 : DDG fallback amélioré ───────────────────────────────────────

def test_ddg_fallback_filters_trackers():
    """
    WEB-03 — Le fallback DDG doit exclure les liens publicitaires et trackers.
    """
    html_page = """
    <html><body>
      <a href="https://doubleclick.net/ads">Pub doubleclick</a>
      <a href="https://facebook.com/share">Partager sur Facebook</a>
      <a href="https://example.com/article-complet">Article complet sur le sujet</a>
      <a href="https://other.com/page">Autre source valide ici</a>
    </body></html>
    """
    client = _DdgLiteClient()
    # Le parsing principal ne trouvera rien (pas de classe result-link)
    # Le fallback doit filtrer doubleclick et facebook
    hits = client._parse(html_page, max_results=5)
    urls = [h.url for h in hits]
    assert not any("doubleclick" in u for u in urls)
    assert not any("facebook" in u for u in urls)
    # Les vraies URLs doivent passer
    assert any("example.com" in u for u in urls)


def test_ddg_fallback_filters_short_titles():
    """
    WEB-03 — Le fallback DDG doit ignorer les ancres avec titre trop court (nav, logo).
    """
    html_page = """
    <html><body>
      <a href="https://example.com/page">OK</a>
      <a href="https://good.com/article">Un article complet sur le sujet</a>
    </body></html>
    """
    client = _DdgLiteClient()
    hits = client._parse(html_page, max_results=5)
    urls = [h.url for h in hits]
    # "OK" fait 2 chars < 8 → filtré
    assert not any("example.com" in u for u in urls)
    # Le bon titre (>= 8 chars) passe
    assert any("good.com" in u for u in urls)


# ── WEB-03 : Tool MCP web_cache_stats ──────────────────────────────────

def test_tool_web_cache_stats_action_stats(tmp_path):
    """
    WEB-03 — Le tool MCP web_cache_stats retourne les stats du cache.
    """
    from core.mcp_tool_handlers import McpToolHandlers
    from core.web_search import WebSearchEngine

    # Instancier un handler minimal
    class _MinimalServer(McpToolHandlers):
        pass
    handler = _MinimalServer()

    mock_cache = MagicMock()
    mock_cache.stats.return_value = {"entries": 3, "size_kb": 12.5, "cache_dir": str(tmp_path)}

    mock_engine = MagicMock()
    mock_engine._cache = mock_cache

    with patch("core.web_search.WebSearchEngine", return_value=mock_engine):
        result = handler._tool_web_cache_stats({"action": "stats"})

    assert result["action"] == "stats"
    assert result["entries"] == 3
    assert result["size_kb"] == 12.5


def test_tool_web_cache_stats_action_clear_expired(tmp_path):
    """
    WEB-03 — clear_expired retourne le nombre d'entrées supprimées.
    """
    from core.mcp_tool_handlers import McpToolHandlers

    class _MinimalServer(McpToolHandlers):
        pass
    handler = _MinimalServer()

    mock_cache = MagicMock()
    mock_cache.clear_expired.return_value = 2
    mock_engine = MagicMock()
    mock_engine._cache = mock_cache

    with patch("core.web_search.WebSearchEngine", return_value=mock_engine):
        result = handler._tool_web_cache_stats({"action": "clear_expired"})

    assert result["action"] == "clear_expired"
    assert result["removed"] == 2
    assert "2" in result["message"]


def test_tool_web_cache_stats_action_invalidate(tmp_path):
    """
    WEB-03 — invalidate retourne deleted=True si l'entrée existait.
    """
    from core.mcp_tool_handlers import McpToolHandlers

    class _MinimalServer(McpToolHandlers):
        pass
    handler = _MinimalServer()

    mock_cache = MagicMock()
    mock_cache.invalidate.return_value = True
    mock_engine = MagicMock()
    mock_engine._cache = mock_cache

    with patch("core.web_search.WebSearchEngine", return_value=mock_engine):
        result = handler._tool_web_cache_stats({"action": "invalidate", "query": "test query"})

    assert result["deleted"] is True
    assert "supprim" in result["message"]


def test_tool_web_cache_stats_invalidate_missing_query():
    """
    WEB-03 — invalidate sans query → ValueError.
    """
    from core.mcp_tool_handlers import McpToolHandlers

    class _MinimalServer(McpToolHandlers):
        pass
    handler = _MinimalServer()

    mock_engine = MagicMock()
    with patch("core.web_search.WebSearchEngine", return_value=mock_engine):
        with pytest.raises(ValueError, match="query"):
            handler._tool_web_cache_stats({"action": "invalidate"})


def test_tool_web_cache_stats_unknown_action():
    """
    WEB-03 — Action inconnue → ValueError.
    """
    from core.mcp_tool_handlers import McpToolHandlers

    class _MinimalServer(McpToolHandlers):
        pass
    handler = _MinimalServer()

    mock_engine = MagicMock()
    with patch("core.web_search.WebSearchEngine", return_value=mock_engine):
        with pytest.raises(ValueError, match="Action inconnue"):
            handler._tool_web_cache_stats({"action": "nuke"})
