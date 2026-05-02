# -*- coding: utf-8-sig -*-
"""
test_refacto_15.py — LCCA V5 Fusion
REFACTO-15 : memory_engine.py découpé en memory_engine_store.py + memory_engine_search.py

18 tests couvrant :
  - memory_engine_store : StoreResult, check_threshold, enrich_payload, extract_content,
                          store_via_adapter, MemoryStoreService
  - memory_engine_search : MemoryEntry, chromadb_query, normalize_entry, MemorySearchService
  - memory_engine : façade (rétrocompat totale — tous les alias privés fonctionnent)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, PropertyMock

# ── Imports directs des sous-modules REFACTO-15 ───────────────────────────────
from core.memory_engine_store import (
    StoreResult,
    MemoryStoreService,
    _THRESHOLD_SOLUTIONS,
    _THRESHOLD_CONTEXT,
    _VALID_COLLECTIONS,
    check_threshold,
    enrich_payload,
    extract_content,
    store_via_adapter,
)
from core.memory_engine_search import (
    MemoryEntry,
    MemorySearchService,
    chromadb_query,
    normalize_entry,
)
from core.memory_engine import MemoryEngine


# ── Helpers fixtures ──────────────────────────────────────────────────────────

def _make_adapter(available: bool = True, cols: dict | None = None) -> MagicMock:
    adapter = MagicMock()
    type(adapter).is_available = PropertyMock(return_value=available)
    adapter.palace_path = "/fake/palace" if available else None
    adapter.lcca_collections = cols or {}
    adapter.search.return_value = []
    return adapter


def _make_col_mock(entries: list) -> MagicMock:
    col = MagicMock()
    col.query.return_value = {
        "ids":       [[e["id"] for e in entries]],
        "documents": [[e["content"] for e in entries]],
        "metadatas": [[e.get("meta", {}) for e in entries]],
        "distances": [[e.get("dist", 0.0) for e in entries]],
    }
    return col


# ═══════════════════════════════════════════════════════════════════════════
# 1-6 : memory_engine_store — fonctions pures
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckThreshold:

    def test_solutions_below_rejects(self) -> None:
        msg = check_threshold("lcca_solutions", {"score": 0.5})
        assert msg is not None
        assert str(_THRESHOLD_SOLUTIONS) in msg

    def test_solutions_at_threshold_passes(self) -> None:
        assert check_threshold("lcca_solutions", {"score": _THRESHOLD_SOLUTIONS}) is None

    def test_context_below_rejects(self) -> None:
        msg = check_threshold("lcca_context", {"score": 0.3})
        assert msg is not None
        assert str(_THRESHOLD_CONTEXT) in msg

    def test_failures_no_score_passes(self) -> None:
        assert check_threshold("lcca_failures", {}) is None

    def test_patches_no_score_passes(self) -> None:
        assert check_threshold("lcca_patches", {}) is None


class TestEnrichPayload:

    def test_adds_metadata(self) -> None:
        enriched = enrich_payload("lcca_failures", {"error": "boom"})
        assert enriched["_collection"] == "lcca_failures"
        assert "_ts" in enriched
        assert enriched["_version"] == "7.0"

    def test_does_not_overwrite_existing(self) -> None:
        enriched = enrich_payload("lcca_patches", {"_version": "custom"})
        assert enriched["_version"] == "custom"


class TestExtractContentModule:

    def test_prefers_code(self) -> None:
        assert extract_content({"code": "def f(): pass", "error": "no"}) == "def f(): pass"

    def test_fallback_to_snippet(self) -> None:
        assert extract_content({"snippet": "x = 1"}) == "x = 1"

    def test_empty_returns_marker(self) -> None:
        assert extract_content({}) == "(empty)"


# ═══════════════════════════════════════════════════════════════════════════
# 7-9 : MemoryStoreService
# ═══════════════════════════════════════════════════════════════════════════

class TestMemoryStoreService:

    def test_invalid_collection_rejected(self) -> None:
        svc = MemoryStoreService(_make_adapter(), enforce_thresholds=False)
        res = svc.store("lcca_unknown", {}, available=True)
        assert res.stored is False
        assert "Collection inconnue" in res.reason

    def test_enforce_threshold_blocks(self) -> None:
        svc = MemoryStoreService(_make_adapter(), enforce_thresholds=True)
        res = svc.store("lcca_solutions", {"score": 0.1, "code": "x"}, available=True)
        assert res.stored is False
        assert str(_THRESHOLD_SOLUTIONS) in res.reason

    def test_unavailable_returns_false(self) -> None:
        svc = MemoryStoreService(_make_adapter(available=False))
        res = svc.store("lcca_failures", {"error": "boom"}, available=False)
        assert res.stored is False
        assert "non disponible" in res.reason.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 10-12 : memory_engine_search — fonctions pures
# ═══════════════════════════════════════════════════════════════════════════

class TestChromedbQuery:

    def test_returns_memory_entries(self) -> None:
        col = _make_col_mock([
            {"id": "1", "content": "def foo(): pass", "meta": {"file": "a.py"}, "dist": 0.1},
        ])
        entries = chromadb_query(col, "lcca_solutions", "def foo", n=5)
        assert len(entries) == 1
        assert entries[0].id == "1"
        assert entries[0].collection == "lcca_solutions"
        assert abs(entries[0].distance - 0.1) < 1e-9

    def test_empty_returns_empty(self) -> None:
        col = _make_col_mock([])
        assert chromadb_query(col, "lcca_solutions", "query", n=5) == []

    def test_chromadb_exception_returns_empty(self) -> None:
        col = MagicMock()
        col.query.side_effect = RuntimeError("ChromaDB down")
        assert chromadb_query(col, "lcca_failures", "query", n=5) == []


class TestNormalizeEntry:

    def test_memory_entry_passthrough(self) -> None:
        e = MemoryEntry(id="x", collection="lcca_solutions", content="hello")
        assert normalize_entry(e, "lcca_solutions") is e

    def test_object_with_content(self) -> None:
        obj = MagicMock()
        obj.content = "some content"
        obj.id = "my_id"
        obj.metadata = {"k": "v"}
        obj.distance = 0.5
        result = normalize_entry(obj, "lcca_solutions")
        assert result.content == "some content"
        assert result.id == "my_id"

    def test_raw_string_fallback(self) -> None:
        result = normalize_entry("raw string", "lcca_failures")
        assert result.content == "raw string"
        assert result.id == "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# 13-15 : MemorySearchService
# ═══════════════════════════════════════════════════════════════════════════

class TestMemorySearchService:

    def test_search_unavailable_returns_empty(self) -> None:
        svc = MemorySearchService(_make_adapter(available=False))
        result = svc.search("query", available=False)
        assert all(v == [] for v in result.values())

    def test_search_patches_unavailable(self) -> None:
        svc = MemorySearchService(_make_adapter(available=False))
        assert svc.search_patches("query", available=False) == []

    def test_search_with_chromadb(self) -> None:
        entries = [{"id": "1", "content": "def foo(): pass", "dist": 0.0}]
        col = _make_col_mock(entries)
        adapter = _make_adapter(cols={"lcca_solutions": col})
        svc = MemorySearchService(adapter)
        result = svc.search("foo", available=True)
        assert len(result["solutions"]) == 1
        assert result["solutions"][0].id == "1"


# ═══════════════════════════════════════════════════════════════════════════
# 16-18 : MemoryEngine façade — rétrocompat
# ═══════════════════════════════════════════════════════════════════════════

class TestMemoryEngineFacade:

    def _make_engine(self, available: bool = True, enforce: bool = False) -> MemoryEngine:
        adapter = _make_adapter(available=available)
        assembler = MagicMock()
        return MemoryEngine(adapter=adapter, context_assembler=assembler, enforce_thresholds=enforce)

    def test_private_aliases_check_threshold(self) -> None:
        engine = self._make_engine()
        # _check_threshold doit déléguer à check_threshold
        result = engine._check_threshold("lcca_solutions", {"score": 0.1})
        assert result is not None

    def test_private_alias_enrich_payload(self) -> None:
        engine = self._make_engine()
        enriched = engine._enrich_payload("lcca_failures", {"error": "boom"})
        assert enriched["_collection"] == "lcca_failures"
        assert "_ts" in enriched

    def test_extract_content_static_alias(self) -> None:
        assert MemoryEngine._extract_content({"code": "pass"}) == "pass"
        assert MemoryEngine._extract_content({}) == "(empty)"
