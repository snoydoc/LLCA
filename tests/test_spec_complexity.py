# -*- coding: utf-8-sig -*-
"""test_spec_complexity.py — 10 tests Sprint 15 (SpecComplexityEstimator).
Sprint 18 — Dette 11 : mocks mis à jour pour retourner les clés normalisées
            de MemoryEngine.search() : "specs" et "failures" (pas lcca_specs/lcca_failures).
            spec_complexity.py lit maintenant result.get("specs") et result.get("failures").
"""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch

from core.spec_complexity import SpecComplexityEstimator, _infer_domain


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mock_mem(has_specs: bool = False, has_failures: bool = False) -> MagicMock:
    """
    Crée un mock de MemoryEngine.

    Sprint 18 — Dette 11 : search() retourne les clés normalisées
    ("specs", "failures", "solutions", "context") pas les noms de collection.
    """
    mem = MagicMock()
    entry = MagicMock()

    def _search_side_effect(query, wing="lcca", n=5):
        return {
            "solutions": [],
            "failures":  [entry] if has_failures else [],
            "context":   [],
            "specs":     [entry] if has_specs else [],
        }

    mem.search.side_effect = _search_side_effect
    return mem


def _make_intent(raw: str = "simple rename", target_files: list | None = None) -> MagicMock:
    intent = MagicMock()
    intent.raw = raw
    intent.details = raw
    intent.target_files = target_files or []
    return intent


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSpecComplexityEstimator:

    def test_should_generate_spec_max_files(self):
        """3 fichiers cibles → +30 pts. Avec domaine connu → pas de +25."""
        mem = _mock_mem(has_specs=True)
        est = SpecComplexityEstimator(mem)
        intent_3 = _make_intent("add feature", target_files=["a.py", "b.py", "c.py"])
        intent_0 = _make_intent("add feature", target_files=[])
        _, score_3 = est.estimate(intent_3)
        _, score_0 = est.estimate(intent_0)
        assert score_3 > score_0
        assert score_3 >= 30

    def test_should_not_generate_simple_rename(self):
        """Rename simple, domaine connu, pas d'échec → score < threshold=60 → False."""
        mem = _mock_mem(has_specs=True, has_failures=False)
        est = SpecComplexityEstimator(mem)
        intent = _make_intent("rename variable x to y", target_files=[])
        with patch("config.SPEC_COMPLEXITY_THRESHOLD", 60):
            need, score = est.estimate(intent)
        assert score < 60
        assert need is False

    def test_complex_keyword_adds_score(self):
        """Mot-clé 'transaction' → score supérieur à sans keyword."""
        mem = _mock_mem(has_specs=True)
        est = SpecComplexityEstimator(mem)
        with patch("config.SPEC_COMPLEXITY_THRESHOLD", 60):
            intent_with    = _make_intent("add transaction support")
            intent_without = _make_intent("add logging")
            _, score_with    = est.estimate(intent_with)
            _, score_without = est.estimate(intent_without)
        assert score_with > score_without

    def test_new_domain_adds_score(self):
        """Domaine absent de la mémoire (specs=[]) → +25 pts vs domaine connu."""
        mem_empty = _mock_mem(has_specs=False)
        mem_known = _mock_mem(has_specs=True)
        est_empty = SpecComplexityEstimator(mem_empty)
        est_known = SpecComplexityEstimator(mem_known)
        intent = _make_intent("add logging")
        with patch("config.SPEC_COMPLEXITY_THRESHOLD", 60):
            _, score_empty = est_empty.estimate(intent)
            _, score_known = est_known.estimate(intent)
        assert score_empty > score_known

    def test_past_failure_adds_score(self):
        """Échec similaire (failures=[entry]) → +15 pts."""
        mem_no_fail = _mock_mem(has_specs=True, has_failures=False)
        mem_fail    = _mock_mem(has_specs=True, has_failures=True)
        est_no   = SpecComplexityEstimator(mem_no_fail)
        est_fail = SpecComplexityEstimator(mem_fail)
        intent = _make_intent("add logging")
        with patch("config.SPEC_COMPLEXITY_THRESHOLD", 60):
            _, score_no   = est_no.estimate(intent)
            _, score_fail = est_fail.estimate(intent)
        assert score_fail > score_no

    def test_score_capped_at_100(self):
        """Tous les critères cumulés → score plafonné à 100."""
        mem = _mock_mem(has_specs=False, has_failures=True)
        est = SpecComplexityEstimator(mem)
        intent = _make_intent(
            "refactor the transaction rollback architecture " + "x" * 110,
            target_files=["a.py", "b.py", "c.py"],
        )
        with patch("config.SPEC_COMPLEXITY_THRESHOLD", 60):
            _, score = est.estimate(intent)
        assert score <= 100

    def test_infer_domain_sandbox(self):
        intent = _make_intent("add docker sandbox support")
        assert _infer_domain(intent) == "sandbox"

    def test_infer_domain_mcp(self):
        intent = _make_intent("fix json-rpc server tool dispatch")
        assert _infer_domain(intent) == "mcp"

    def test_infer_domain_fallback(self):
        intent = _make_intent("update the readme file")
        assert _infer_domain(intent) == "global"

    def test_memory_search_called(self):
        """search() est appelé au moins une fois lors de estimate()."""
        mem = _mock_mem(has_specs=False)
        est = SpecComplexityEstimator(mem)
        with patch("config.SPEC_COMPLEXITY_THRESHOLD", 60):
            est.estimate(_make_intent("add logging"))
        assert mem.search.called
