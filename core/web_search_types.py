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
