# -*- coding: utf-8-sig -*-
"""
tests/test_refacto_03.py -- Sprint REFACTO-03 : ObserverAnalyzer

Verifie que la logique d'analyse extraite de observer_agent.py
fonctionne correctement dans ObserverAnalyzer, et que
ObserverAgent deleguent correctement vers self._analyzer.

Retrocompat : les tests de test_observer_agent.py existants
ne doivent pas etre modifies (les wrappers _find_low_quality /
_find_duplicates sont conserves sur ObserverAgent).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.agents.observer_analyzer import ObserverAnalyzer, _is_duplicate, _build_snapshot
from core.agents.observer_agent import ObserverAgent
from core.agents.a2a_bus import A2ALocalBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_skill(id_: str, body: str, score: float) -> dict:
    return {"id": id_, "body": body, "score": score, "metadata": {}}


def _make_agent() -> ObserverAgent:
    bus = A2ALocalBus(db_path=":memory:")
    return ObserverAgent.create(bus=bus, receipts_dir=None)


# ---------------------------------------------------------------------------
# TestIsDuplicate (module-level helper)
# ---------------------------------------------------------------------------

class TestIsDuplicate:
    """Tests de la fonction _is_duplicate (module-level)."""

    def test_identical_bodies(self):
        a = {"body": "def foo(): pass"}
        b = {"body": "def foo(): pass"}
        assert _is_duplicate(a, b, threshold=0.95) is True

    def test_disjoint_bodies(self):
        a = {"body": "alpha beta gamma"}
        b = {"body": "delta epsilon zeta"}
        assert _is_duplicate(a, b, threshold=0.95) is False

    def test_partial_overlap_below_threshold(self):
        a = {"body": "foo bar baz qux"}
        b = {"body": "foo bar spam eggs"}
        # intersection=2 union=6 -> jaccard=0.333 < 0.95
        assert _is_duplicate(a, b, threshold=0.95) is False

    def test_empty_body_returns_false(self):
        a = {"body": ""}
        b = {"body": "def foo(): pass"}
        assert _is_duplicate(a, b, threshold=0.5) is False

    def test_uses_code_key_fallback(self):
        a = {"code": "x = 1"}
        b = {"code": "x = 1"}
        assert _is_duplicate(a, b, threshold=0.95) is True


# ---------------------------------------------------------------------------
# TestBuildSnapshot (module-level helper)
# ---------------------------------------------------------------------------

class TestBuildSnapshot:
    """Tests de la fonction _build_snapshot (module-level)."""

    def test_all_keys_present(self):
        snap = _build_snapshot(10, ["id1"], [("a", "b")], ["r1"])
        expected_keys = {
            "skills_total", "low_quality_ids", "duplicate_pairs",
            "archived_ids", "low_quality_count", "duplicate_count",
            "archived_count", "observed_at",
        }
        assert expected_keys.issubset(snap.keys())

    def test_counts_correct(self):
        snap = _build_snapshot(5, ["x", "y"], [("a", "b"), ("c", "d")], ["z"])
        assert snap["skills_total"] == 5
        assert snap["low_quality_count"] == 2
        assert snap["duplicate_count"] == 2
        assert snap["archived_count"] == 1

    def test_duplicate_pairs_serializable(self):
        """Les paires tuples sont converties en listes (JSON-safe)."""
        snap = _build_snapshot(0, [], [("a", "b")], [])
        assert snap["duplicate_pairs"] == [["a", "b"]]


# ---------------------------------------------------------------------------
# TestObserverAnalyzer
# ---------------------------------------------------------------------------

class TestObserverAnalyzer:
    """Tests directs de ObserverAnalyzer."""

    def _make_analyzer(self, min_score=40, max_sim=0.95):
        return ObserverAnalyzer(min_skill_score=min_score, max_duplicate_sim=max_sim)

    def test_find_low_quality_below_threshold(self):
        analyzer = self._make_analyzer(min_score=50)
        skills = [
            _make_skill("a", "foo", 30),
            _make_skill("b", "bar", 60),
            _make_skill("c", "baz", 20),
        ]
        result = analyzer.find_low_quality(skills)
        assert set(result) == {"a", "c"}

    def test_find_low_quality_all_pass(self):
        analyzer = self._make_analyzer(min_score=20)
        skills = [_make_skill("a", "foo", 50), _make_skill("b", "bar", 80)]
        assert analyzer.find_low_quality(skills) == []

    def test_find_low_quality_override_min_score(self):
        """min_score passe en parametre override la config de l'analyzer."""
        analyzer = self._make_analyzer(min_score=40)
        skills = [_make_skill("a", "foo", 45)]
        # Override a 50 -> 45 < 50 -> low quality
        result = analyzer.find_low_quality(skills, min_score=50)
        assert "a" in result

    def test_find_duplicates_identical(self):
        analyzer = self._make_analyzer(max_sim=0.9)
        skills = [
            _make_skill("a", "def foo(): return 1", 80),
            _make_skill("b", "def foo(): return 1", 80),
        ]
        pairs = analyzer.find_duplicates(skills)
        assert len(pairs) == 1
        assert set(pairs[0]) == {"a", "b"}

    def test_find_duplicates_no_match(self):
        analyzer = self._make_analyzer(max_sim=0.9)
        skills = [
            _make_skill("a", "alpha omega delta sigma", 80),
            _make_skill("b", "zeta lambda kappa theta", 80),
        ]
        assert analyzer.find_duplicates(skills) == []

    def test_find_duplicates_override_max_sim(self):
        """max_sim passe en parametre override la config."""
        analyzer = self._make_analyzer(max_sim=0.95)
        skills = [
            _make_skill("a", "foo bar", 80),
            _make_skill("b", "foo bar", 80),
        ]
        # max_sim=1.1 -> jamais duplique
        assert analyzer.find_duplicates(skills, max_sim=1.1) == []

    def test_build_snapshot_delegates(self):
        analyzer = self._make_analyzer()
        snap = analyzer.build_snapshot(3, ["x"], [("a", "b")], [])
        assert snap["skills_total"] == 3
        assert snap["low_quality_ids"] == ["x"]
        assert snap["duplicate_pairs"] == [["a", "b"]]

    def test_empty_skills_list(self):
        analyzer = self._make_analyzer()
        assert analyzer.find_low_quality([]) == []
        assert analyzer.find_duplicates([]) == []


# ---------------------------------------------------------------------------
# TestObserverAgentDelegation (retrocompat)
# ---------------------------------------------------------------------------

class TestObserverAgentDelegation:
    """Verifie que ObserverAgent delegue vers self._analyzer (REFACTO-03)."""

    def test_observer_has_analyzer(self):
        """ObserverAgent possede bien un attribut _analyzer."""
        agent = _make_agent()
        assert hasattr(agent, "_analyzer")
        assert isinstance(agent._analyzer, ObserverAnalyzer)

    def test_wrapper_find_low_quality(self):
        """_find_low_quality() sur ObserverAgent delegue a _analyzer."""
        agent = _make_agent()
        skills = [_make_skill("low", "xxx", 10), _make_skill("ok", "yyy", 80)]
        result = agent._find_low_quality(skills, min_score=50)
        assert "low" in result
        assert "ok" not in result

    def test_wrapper_find_duplicates(self):
        """_find_duplicates() sur ObserverAgent delegue a _analyzer."""
        agent = _make_agent()
        skills = [
            _make_skill("a", "hello world test", 80),
            _make_skill("b", "hello world test", 80),
        ]
        pairs = agent._find_duplicates(skills, max_sim=0.9)
        assert len(pairs) == 1

    def test_run_task_uses_analyzer(self):
        """run_task() appelle bien find_low_quality et find_duplicates via _analyzer."""
        agent = _make_agent()
        # On spy l'analyzer
        agent._analyzer.find_low_quality = MagicMock(return_value=[])
        agent._analyzer.find_duplicates = MagicMock(return_value=[])
        agent._analyzer.build_snapshot = MagicMock(return_value={
            "skills_total": 0, "low_quality_ids": [], "duplicate_pairs": [],
            "archived_ids": [], "low_quality_count": 0, "duplicate_count": 0,
            "archived_count": 0, "observed_at": "2026-04-21T00:00:00+00:00",
        })
        from core.agents.a2a_bus import TaskContract
        contract = TaskContract(
            task_id="t001",
            intent="observe",
            domain="global",
            source_agent="orchestrator",
            target_agent="observer",
        )
        result = agent.run_task(contract)
        assert result.success is True
        agent._analyzer.find_low_quality.assert_called_once()
        agent._analyzer.find_duplicates.assert_called_once()
