# -*- coding: utf-8-sig -*-
"""
MemoryEngine V7 — Façade MemPalace pour les 6 collections LCCA.

REFACTO-15 : orchestration légère.
  - Logique de stockage    → memory_engine_store.py (MemoryStoreService)
  - Logique de recherche   → memory_engine_search.py (MemorySearchService)

Architecture : 6 collections V7/V8

  lcca_solutions  (Layer 1 — compressed)  Code validé          seuil score >= 0.8
  lcca_failures   (Layer 2 — scoped)      Erreurs + correctifs  toujours stocker
  lcca_context    (Layer 2 — scoped)      Snippets récents      seuil score >= 0.6
  lcca_patches    (Layer 3 — deep)        Historique complet TX toujours stocker
  lcca_specs      (Spec Layer)            Specs validées        toujours stocker
  lcca_skills     (V8 — SkillLibrary)     Skills extraits       toujours stocker

Usage minimal::

    engine = MemoryEngine()
    engine.store("lcca_failures", {"error": "SyntaxError", "file": "foo.py"})
    results = engine.search("SyntaxError import", n=3)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

# ── Imports des sous-modules REFACTO-15 ──────────────────────────────────────
from core.memory_engine_store import (
    MemoryStoreService,
    StoreResult,
    _THRESHOLD_SOLUTIONS,
    _THRESHOLD_CONTEXT,
    _VALID_COLLECTIONS,
    check_threshold,
    enrich_payload,
    extract_content,
    store_via_adapter,
)
from core.memory_engine_search import (
    MemorySearchService,
    MemoryEntry,
    chromadb_query,
    normalize_entry,
)

log = logging.getLogger("lcca.memory_engine")


class MemoryEngine:
    """
    Façade MemPalace V7 — gère les 6 collections LCCA.

    REFACTO-15 : délègue à MemoryStoreService et MemorySearchService.

    Args:
        adapter:            Instance ExistingMemPalaceAdapter (optionnel).
        context_assembler:  Instance ContextAssembler (optionnel).
        enforce_thresholds: Si True, les seuils bloquent le stockage (V2).
    """

    def __init__(
        self,
        adapter=None,
        context_assembler=None,
        enforce_thresholds: bool = False,
    ) -> None:
        if adapter is None:
            from core.mempalace_adapter import ExistingMemPalaceAdapter
            adapter = ExistingMemPalaceAdapter()
        self.adapter = adapter

        if context_assembler is None:
            from core.context_assembler import ContextAssembler
            context_assembler = ContextAssembler(palace=None)
        self.context_assembler = context_assembler

        self.enforce_thresholds = enforce_thresholds
        self._available = self.adapter.is_available

        # Sous-services REFACTO-15
        self._store_svc  = MemoryStoreService(adapter, enforce_thresholds)
        self._search_svc = MemorySearchService(adapter)

        if self._available:
            log.info("MemoryEngine: MemPalace disponible à %s", self.adapter.palace_path)
        else:
            log.warning("MemoryEngine: MemPalace non disponible — opérations silencieuses")

    # ── Propriété ─────────────────────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """True si le MemPalace sous-jacent est connecté."""
        return self._available

    # ── API publique : search ─────────────────────────────────────────────────

    def search(
        self,
        query: str,
        wing: str = "lcca",
        n: int = 5,
    ) -> Dict[str, List[MemoryEntry]]:
        """Recherche cross-collection dans les 5 collections LCCA."""
        return self._search_svc.search(query, wing=wing, n=n, available=self._available)

    def search_patches(
        self,
        query: str,
        wing: str = "lcca",
        n: int = 5,
    ) -> List[MemoryEntry]:
        """Recherche dans lcca_patches (historique complet TX)."""
        return self._search_svc.search_patches(query, wing=wing, n=n, available=self._available)

    # ── API publique : store ──────────────────────────────────────────────────

    def store(
        self,
        collection: str,
        payload: Dict[str, Any],
    ) -> StoreResult:
        """Stocke une entrée dans une collection LCCA."""
        return self._store_svc.store(collection, payload, self._available)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def store_solution(self, code: str, score: float, metadata: Optional[Dict] = None) -> StoreResult:
        return self._store_svc.store_solution(self._available, code, score, metadata)

    def store_failure(self, error: str, file: str, metadata: Optional[Dict] = None) -> StoreResult:
        return self._store_svc.store_failure(self._available, error, file, metadata)

    def store_patch(self, tx_id: str, files: List[str], metadata: Optional[Dict] = None) -> StoreResult:
        return self._store_svc.store_patch(self._available, tx_id, files, metadata)

    def store_context(self, snippet: str, score: float, metadata: Optional[Dict] = None) -> StoreResult:
        return self._store_svc.store_context(self._available, snippet, score, metadata)

    # ── Méthodes privées — aliases rétrocompat (pour tests existants) ─────────

    def _check_threshold(self, collection: str, payload: Dict) -> Optional[str]:
        return check_threshold(collection, payload)

    def _enrich_payload(self, collection: str, payload: Dict) -> Dict:
        return enrich_payload(collection, payload)

    def _store_via_adapter(self, collection: str, payload: Dict) -> str:
        return store_via_adapter(self.adapter, collection, payload)

    def _search_collection(self, collection: str, query: str, wing: str, n: int) -> List[MemoryEntry]:
        return self._search_svc._search_collection(collection, query, wing=wing, n=n)

    def _chromadb_query(self, col: Any, collection: str, query: str, n: int) -> List[MemoryEntry]:
        return chromadb_query(col, collection, query, n)

    def _normalize_entry(self, raw: Any, collection: str) -> MemoryEntry:
        return normalize_entry(raw, collection)

    @staticmethod
    def _extract_content(payload: Dict) -> str:
        return extract_content(payload)
