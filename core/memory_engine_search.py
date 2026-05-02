# -*- coding: utf-8-sig -*-
"""
memory_engine_search.py — REFACTO-15
Extrait de memory_engine.py : logique de recherche dans les collections LCCA.

Responsabilité unique : lecture / requête sémantique.
  - MemoryEntry dataclass
  - _chromadb_query()      : query ChromaDB + normalisation
  - _normalize_entry()     : normalise un objet brut en MemoryEntry
  - MemorySearchService    : façade search() + search_patches()
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

log = logging.getLogger("lcca.memory_engine")


@dataclass
class MemoryEntry:
    """
    Entrée de mémoire normalisée.

    Attributes:
        id:         Identifiant unique dans la collection.
        collection: Nom de la collection source.
        content:    Contenu textuel de l'entrée.
        metadata:   Métadonnées associées (ex: score, file, model).
        distance:   Score de similarité (0 = identique, plus grand = moins proche).
    """
    id:         str
    collection: str
    content:    str
    metadata:   Dict[str, Any] = field(default_factory=dict)
    distance:   float = 0.0


# ── Fonctions pures ───────────────────────────────────────────────────────────

def chromadb_query(col: Any, collection: str, query: str, n: int) -> List[MemoryEntry]:
    """Lance une query ChromaDB et normalise les résultats en MemoryEntry."""
    try:
        results = col.query(query_texts=[query], n_results=max(1, n))
        entries: List[MemoryEntry] = []

        ids       = results.get("ids",       [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            entries.append(MemoryEntry(
                id=str(doc_id),
                collection=collection,
                content=documents[i] if i < len(documents) else "",
                metadata=metadatas[i] if i < len(metadatas) else {},
                distance=float(distances[i]) if i < len(distances) else 0.0,
            ))
        return entries

    except Exception as exc:  # noqa: BLE001
        log.debug("chromadb_query(%s): %s", collection, exc)
        return []


def normalize_entry(raw: Any, collection: str) -> MemoryEntry:
    """Normalise un objet brut retourné par adapter.search() en MemoryEntry."""
    if isinstance(raw, MemoryEntry):
        return raw
    if hasattr(raw, "content"):
        return MemoryEntry(
            id=getattr(raw, "id", "unknown"),
            collection=collection,
            content=str(raw.content),
            metadata=getattr(raw, "metadata", {}),
            distance=getattr(raw, "distance", 0.0),
        )
    return MemoryEntry(id="unknown", collection=collection, content=str(raw))


# ── MemorySearchService ───────────────────────────────────────────────────────

class MemorySearchService:
    """
    Gère les opérations de recherche dans les collections LCCA.

    Injecté dans MemoryEngine.
    """

    # Mappage clé de résultat → nom de collection ChromaDB
    _SEARCH_COLLECTIONS = (
        ("solutions", "lcca_solutions"),
        ("failures",  "lcca_failures"),
        ("context",   "lcca_context"),
        ("specs",     "lcca_specs"),
        ("skills",    "lcca_skills"),
    )

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def search(
        self,
        query: str,
        wing: str = "lcca",
        n: int = 5,
        available: bool = True,
    ) -> Dict[str, List[MemoryEntry]]:
        """
        Recherche cross-collection dans les 5 collections LCCA.

        Returns:
            Dict {"solutions": [...], "failures": [...], "context": [...], "specs": [...], "skills": [...]}
            Retourne des listes vides si MemPalace non disponible.
        """
        result: Dict[str, List[MemoryEntry]] = {k: [] for k, _ in self._SEARCH_COLLECTIONS}

        if not available:
            return result

        for key, collection in self._SEARCH_COLLECTIONS:
            result[key] = self._search_collection(collection, query, wing=wing, n=n)

        return result

    def search_patches(
        self,
        query: str,
        wing: str = "lcca",
        n: int = 5,
        available: bool = True,
    ) -> List[MemoryEntry]:
        """Recherche dans lcca_patches (historique complet TX)."""
        if not available:
            return []
        return self._search_collection("lcca_patches", query, wing=wing, n=n)

    def _search_collection(
        self,
        collection: str,
        query: str,
        wing: str,
        n: int,
    ) -> List[MemoryEntry]:
        """Recherche dans une collection LCCA via ChromaDB ou adapter.search()."""
        lcca_cols = getattr(self._adapter, "lcca_collections", {})
        col = lcca_cols.get(collection)

        if col is not None:
            return chromadb_query(col, collection, query, n)

        # Fallback adapter
        raw = self._adapter.search(query, wing=wing, n_results=n)
        return [normalize_entry(e, collection) for e in raw]
