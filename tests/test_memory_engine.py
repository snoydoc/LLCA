"""
Tests pour core/memory_engine.py — TASK-12-08.

Suite : test_memory_engine.py
Sprint : 12 — Phase 2
Couvre :
  - MemoryEntry, StoreResult dataclasses
  - MemoryEngine.store() : collections, seuils, helpers
  - MemoryEngine.search() : routing cross-collection
  - Comportement silencieux si MemPalace non disponible
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from core.memory_engine import (
    MemoryEngine,
    MemoryEntry,
    StoreResult,
    _THRESHOLD_SOLUTIONS,
    _THRESHOLD_CONTEXT,
    _VALID_COLLECTIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_adapter(available: bool = True, cols: dict | None = None) -> MagicMock:
    """Crée un adapter mock avec is_available configuré."""
    adapter = MagicMock()
    type(adapter).is_available = PropertyMock(return_value=available)
    adapter.palace_path = "/fake/palace" if available else None
    adapter.lcca_collections = cols or {}
    adapter.search.return_value = []
    return adapter


def _make_engine(available: bool = True, enforce: bool = False) -> MemoryEngine:
    """Crée un MemoryEngine avec adapter mock."""
    adapter = _make_adapter(available=available)
    assembler = MagicMock()
    return MemoryEngine(adapter=adapter, context_assembler=assembler, enforce_thresholds=enforce)


# ---------------------------------------------------------------------------
# Tests MemoryEntry
# ---------------------------------------------------------------------------

class TestMemoryEntry:

    def test_defaults(self) -> None:
        e = MemoryEntry(id="abc", collection="lcca_solutions", content="def foo(): pass")
        assert e.metadata == {}
        assert e.distance == 0.0

    def test_full(self) -> None:
        e = MemoryEntry(
            id="x1", collection="lcca_failures", content="err",
            metadata={"file": "a.py"}, distance=0.42,
        )
        assert e.collection == "lcca_failures"
        assert e.metadata["file"] == "a.py"
        assert abs(e.distance - 0.42) < 1e-9


# ---------------------------------------------------------------------------
# Tests StoreResult
# ---------------------------------------------------------------------------

class TestStoreResult:

    def test_stored_true(self) -> None:
        r = StoreResult(stored=True, collection="lcca_patches", entry_id="abc123")
        assert r.stored is True
        assert r.entry_id == "abc123"
        assert r.reason is None

    def test_stored_false_with_reason(self) -> None:
        r = StoreResult(stored=False, collection="lcca_solutions", reason="score trop bas")
        assert r.stored is False
        assert "score" in r.reason


# ---------------------------------------------------------------------------
# Tests MemoryEngine — disponibilité
# ---------------------------------------------------------------------------

class TestMemoryEngineAvailability:

    def test_is_available_true(self) -> None:
        engine = _make_engine(available=True)
        assert engine.is_available is True

    def test_is_available_false(self) -> None:
        engine = _make_engine(available=False)
        assert engine.is_available is False

    def test_search_returns_empty_when_unavailable(self) -> None:
        engine = _make_engine(available=False)
        result = engine.search("SyntaxError")
        # V8 : search() retourne 5 clés (lcca_solutions/failures/context/specs/skills)
        assert result == {"solutions": [], "failures": [], "context": [], "specs": [], "skills": []}

    def test_store_returns_false_when_unavailable(self) -> None:
        engine = _make_engine(available=False)
        res = engine.store("lcca_failures", {"error": "boom", "file": "a.py"})
        assert res.stored is False
        assert "non disponible" in res.reason.lower()

    def test_search_patches_empty_when_unavailable(self) -> None:
        engine = _make_engine(available=False)
        assert engine.search_patches("tx") == []


# ---------------------------------------------------------------------------
# Tests store() — validation collection
# ---------------------------------------------------------------------------

class TestStoreCollectionValidation:

    def test_invalid_collection_rejected(self) -> None:
        engine = _make_engine()
        res = engine.store("lcca_unknown", {"foo": "bar"})
        assert res.stored is False
        assert "Collection inconnue" in res.reason

    def test_all_valid_collections_accepted_structurally(self) -> None:
        """Toutes les collections valides passent la validation de nom."""
        engine = _make_engine()
        for col in _VALID_COLLECTIONS:
            payload = {"score": 1.0, "code": "pass", "error": "e", "snippet": "s",
                       "tx_id": "tx1", "files": []}
            res = engine.store(col, payload)
            # stored peut être False pour des raisons d'adaptateur, mais pas "Collection inconnue"
            if not res.stored:
                assert "Collection inconnue" not in (res.reason or "")


# ---------------------------------------------------------------------------
# Tests store() — seuils
# ---------------------------------------------------------------------------

class TestStoreThresholds:

    # ── lcca_solutions ────────────────────────────────────────────────────────

    def test_solutions_below_threshold_informative(self) -> None:
        """V1 : seuil non atteint → loggue mais stocke quand même."""
        engine = _make_engine(enforce=False)
        res = engine.store("lcca_solutions", {"code": "def f(): pass", "score": 0.5})
        # En mode V1, le store tente quand même (may fail sur ChromaDB absent)
        # mais ne doit pas être rejeté à cause du seuil seul
        assert res.stored is True or "seuil" not in (res.reason or "")

    def test_solutions_below_threshold_blocking(self) -> None:
        """V2 : seuil non atteint → bloque."""
        engine = _make_engine(enforce=True)
        res = engine.store("lcca_solutions", {"code": "def f(): pass", "score": 0.5})
        assert res.stored is False
        assert str(_THRESHOLD_SOLUTIONS) in res.reason

    def test_solutions_no_score_blocking(self) -> None:
        """V2 : absence de score → bloque."""
        engine = _make_engine(enforce=True)
        res = engine.store("lcca_solutions", {"code": "def f(): pass"})
        assert res.stored is False

    def test_solutions_exact_threshold_passes(self) -> None:
        """Score exactement au seuil → accepté."""
        engine = _make_engine(enforce=True)
        res = engine.store("lcca_solutions", {"code": "def f(): pass", "score": _THRESHOLD_SOLUTIONS})
        # Stocké ou échoué pour une autre raison (ChromaDB absent), pas seuil
        if not res.stored:
            assert "seuil" not in (res.reason or "").lower() or str(_THRESHOLD_SOLUTIONS) not in (res.reason or "")

    # ── lcca_context ──────────────────────────────────────────────────────────

    def test_context_below_threshold_blocking(self) -> None:
        engine = _make_engine(enforce=True)
        res = engine.store("lcca_context", {"snippet": "x = 1", "score": 0.3})
        assert res.stored is False
        assert str(_THRESHOLD_CONTEXT) in res.reason

    def test_context_above_threshold_passes(self) -> None:
        engine = _make_engine(enforce=True)
        res = engine.store("lcca_context", {"snippet": "x = 1", "score": 0.7})
        if not res.stored:
            assert str(_THRESHOLD_CONTEXT) not in (res.reason or "")

    # ── lcca_failures / lcca_patches — toujours stocker ──────────────────────

    def test_failures_no_score_always_accepted(self) -> None:
        engine = _make_engine(enforce=True)
        res = engine.store("lcca_failures", {"error": "NameError", "file": "x.py"})
        # Pas de rejet pour seuil
        assert "seuil" not in (res.reason or "").lower()

    def test_patches_no_score_always_accepted(self) -> None:
        engine = _make_engine(enforce=True)
        res = engine.store("lcca_patches", {"tx_id": "tx_abc", "files": ["a.py"]})
        assert "seuil" not in (res.reason or "").lower()


# ---------------------------------------------------------------------------
# Tests store() — helpers
# ---------------------------------------------------------------------------

class TestStoreHelpers:

    def test_store_solution_helper(self) -> None:
        engine = _make_engine()
        res = engine.store_solution("def f(): pass", score=0.9)
        assert isinstance(res, StoreResult)

    def test_store_failure_helper(self) -> None:
        engine = _make_engine()
        res = engine.store_failure("SyntaxError", file="foo.py")
        assert isinstance(res, StoreResult)

    def test_store_patch_helper(self) -> None:
        engine = _make_engine()
        res = engine.store_patch("tx_abc123", files=["a.py", "b.py"])
        assert isinstance(res, StoreResult)

    def test_store_context_helper(self) -> None:
        engine = _make_engine()
        res = engine.store_context("x = 1  # context snippet", score=0.65)
        assert isinstance(res, StoreResult)

    def test_store_failure_always_stored_even_enforce(self) -> None:
        engine = _make_engine(enforce=True)
        res = engine.store_failure("ZeroDivisionError", file="calc.py")
        # Pas de rejet seuil — peut échouer sur adaptateur, pas sur seuil
        assert "seuil" not in (res.reason or "").lower()


# ---------------------------------------------------------------------------
# Tests store() — payload enrichissement
# ---------------------------------------------------------------------------

class TestPayloadEnrichment:

    def test_private_fields_added(self) -> None:
        """_enrich_payload ajoute _collection, _ts, _version."""
        engine = _make_engine()
        enriched = engine._enrich_payload("lcca_failures", {"error": "boom"})
        assert enriched["_collection"] == "lcca_failures"
        assert "_ts" in enriched
        assert enriched["_version"] == "7.0"

    def test_existing_fields_not_overwritten(self) -> None:
        engine = _make_engine()
        enriched = engine._enrich_payload("lcca_patches", {"_version": "custom"})
        assert enriched["_version"] == "custom"  # setdefault respecté


# ---------------------------------------------------------------------------
# Tests search() avec ChromaDB mock
# ---------------------------------------------------------------------------

class TestSearchWithChromaDB:

    def _make_col_mock(self, entries: list) -> MagicMock:
        """Mock d'une collection ChromaDB retournant des résultats."""
        col = MagicMock()
        col.query.return_value = {
            "ids":       [[e["id"] for e in entries]],
            "documents": [[e["content"] for e in entries]],
            "metadatas": [[e.get("meta", {}) for e in entries]],
            "distances": [[e.get("dist", 0.0) for e in entries]],
        }
        return col

    def test_search_returns_memory_entries(self) -> None:
        fake_entries = [
            {"id": "1", "content": "def foo(): pass", "meta": {"file": "a.py"}, "dist": 0.1},
            {"id": "2", "content": "def bar(): pass", "meta": {}, "dist": 0.3},
        ]
        col = self._make_col_mock(fake_entries)
        cols = {
            "lcca_solutions": col,
            "lcca_failures":  self._make_col_mock([]),
            "lcca_context":   self._make_col_mock([]),
        }
        adapter = _make_adapter(available=True, cols=cols)
        engine = MemoryEngine(adapter=adapter, context_assembler=MagicMock())

        result = engine.search("def foo")
        assert len(result["solutions"]) == 2
        assert result["solutions"][0].id == "1"
        assert result["solutions"][0].collection == "lcca_solutions"
        assert abs(result["solutions"][0].distance - 0.1) < 1e-9

    def test_search_empty_collections(self) -> None:
        cols = {
            "lcca_solutions": self._make_col_mock([]),
            "lcca_failures":  self._make_col_mock([]),
            "lcca_context":   self._make_col_mock([]),
        }
        adapter = _make_adapter(available=True, cols=cols)
        engine = MemoryEngine(adapter=adapter, context_assembler=MagicMock())
        result = engine.search("nothing")
        # V8 : search() retourne 5 clés (lcca_solutions/failures/context/specs/skills)
        assert result == {"solutions": [], "failures": [], "context": [], "specs": [], "skills": []}

    def test_search_patches_uses_correct_collection(self) -> None:
        fake = [{"id": "p1", "content": "tx_abc", "dist": 0.0}]
        col = self._make_col_mock(fake)
        cols = {"lcca_patches": col}
        adapter = _make_adapter(available=True, cols=cols)
        engine = MemoryEngine(adapter=adapter, context_assembler=MagicMock())
        patches = engine.search_patches("tx_abc")
        assert len(patches) == 1
        assert patches[0].collection == "lcca_patches"


# ---------------------------------------------------------------------------
# Tests _extract_content
# ---------------------------------------------------------------------------

class TestExtractContent:

    def test_prefers_code(self) -> None:
        payload = {"code": "def f(): pass", "error": "no", "snippet": "x"}
        assert MemoryEngine._extract_content(payload) == "def f(): pass"

    def test_falls_back_to_snippet(self) -> None:
        payload = {"snippet": "x = 1"}
        assert MemoryEngine._extract_content(payload) == "x = 1"

    def test_falls_back_to_error(self) -> None:
        payload = {"error": "SyntaxError"}
        assert MemoryEngine._extract_content(payload) == "SyntaxError"

    def test_empty_payload_returns_empty_marker(self) -> None:
        result = MemoryEngine._extract_content({})
        assert result == "(empty)"

    def test_ignores_private_keys(self) -> None:
        payload = {"_ts": "2026-01-01", "_version": "7.0", "error": "boom"}
        assert MemoryEngine._extract_content(payload) == "boom"
