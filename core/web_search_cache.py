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
    "tutoriel", "documentation", "api", "installer",
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
