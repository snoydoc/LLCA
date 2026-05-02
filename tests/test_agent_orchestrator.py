# -*- coding: utf-8-sig -*-
"""
Tests Sprint V8-06 -- AgentOrchestrator

Couverture (12 tests) :
    A. Helpers module-level (3 tests)
        - _make_task_id : unicite + prefixe "orch_"
        - _detect_stagnation : pas assez d'historique / stagnation / progression
    B. OrchestratorResult (2 tests)
        - is_ok() success vs echec
        - champs par defaut
    C. AgentOrchestrator.create (1 test)
        - factory cree les 4 agents + expose les attrs attendus
    D. AgentOrchestrator.run -- pipeline nominal (2 tests)
        - Architect success + Coder success + Reviewer success + Tester success -> OrchestratorResult.success=True
        - Architect failure -> OrchestratorResult.success=False apres max_iterations
    E. AgentOrchestrator.run -- KarpathyLoop (3 tests)
        - Reviewer rejection -> reflexion injectee + retry
        - Tester rejection -> reflexion injectee + retry
        - Stagnation (V8-Regle-18) -> arret anticipé avant max_iterations
    F. AgentOrchestrator.run -- timeout + SkillLibrary (1 test)
        - timeout_sec=0 -> OrchestratorResult.timed_out=True
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.agent_orchestrator import (
    AgentOrchestrator,
    OrchestratorResult,
    _detect_stagnation,
    _make_task_id,
)
from core.agents.base_agent import AgentResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _bus() -> A2ALocalBus:
    return A2ALocalBus(db_path=":memory:")


def _ok_result(**kwargs) -> AgentResult:
    return AgentResult(success=True, payload=kwargs)


def _fail_result(error="fail", **kwargs) -> AgentResult:
    return AgentResult(success=False, error=error, payload=kwargs)


def _make_orchestrator(
    bus=None,
    arch_results=None,
    coder_results=None,
    reviewer_results=None,
    tester_results=None,
    skill_lib=None,
    max_iterations=3,
    max_stagnation=2,
    timeout_sec=60,
):
    """
    Cree un AgentOrchestrator avec les 4 agents mockés.

    arch_results / coder_results / reviewer_results / tester_results :
        liste de AgentResult retournes sequentiellement par run_task().
        Si la liste est epuisee, le dernier element est rejoue.
    """
    if bus is None:
        bus = _bus()

    def _make_side_effect(results):
        results = list(results) if results else [_ok_result()]
        calls = [0]
        def side_effect(*args, **kwargs):
            idx = min(calls[0], len(results) - 1)
            calls[0] += 1
            return results[idx]
        return side_effect

    arch = MagicMock()
    arch.card = MagicMock()
    arch.card.name = "architect"
    arch.run_task.side_effect = _make_side_effect(
        arch_results or [_ok_result(dispatched=["sub_001"], sub_contracts=1, specs_found=0)]
    )

    coder = MagicMock()
    coder.card = MagicMock()
    coder.card.name = "coder"
    coder.run_task.side_effect = _make_side_effect(
        coder_results or [_ok_result(task_id="sub_001", patch={}, edit_result={}, skills_used=0)]
    )

    reviewer = MagicMock()
    reviewer.card = MagicMock()
    reviewer.card.name = "reviewer"
    reviewer.run_task.side_effect = _make_side_effect(
        reviewer_results or [_ok_result(task_id="sub_001", reviewer_ok=True, forwarded_to="tester")]
    )

    tester = MagicMock()
    tester.card = MagicMock()
    tester.card.name = "tester"
    tester.run_task.side_effect = _make_side_effect(
        tester_results or [_ok_result(task_id="sub_001", sandbox_passed=True, quality_score=85, tester_ok=True)]
    )

    return AgentOrchestrator(
        bus=bus,
        architect=arch,
        coder=coder,
        reviewer=reviewer,
        tester=tester,
        skill_library=skill_lib,
        max_iterations=max_iterations,
        max_stagnation=max_stagnation,
        timeout_sec=timeout_sec,
    )


# ---------------------------------------------------------------------------
# A. Helpers module-level
# ---------------------------------------------------------------------------

class TestMakeTaskId:
    def test_prefix_orch(self):
        tid = _make_task_id("foo intent")
        assert tid.startswith("orch_")

    def test_unique(self):
        # Deux appels successifs donnent des IDs differents (timestamp monotonique)
        t1 = _make_task_id("same intent")
        time.sleep(0.001)
        t2 = _make_task_id("same intent")
        assert t1 != t2


class TestDetectStagnation:
    def test_too_short_history_returns_false(self):
        assert _detect_stagnation([0, 0], max_stagnation=3) is False

    def test_all_same_returns_true(self):
        assert _detect_stagnation([42, 42, 42], max_stagnation=3) is True

    def test_improving_returns_false(self):
        assert _detect_stagnation([10, 50, 80], max_stagnation=3) is False

    def test_last_n_same_returns_true(self):
        # Seulement les 3 derniers comptent
        assert _detect_stagnation([10, 20, 5, 5, 5], max_stagnation=3) is True


# ---------------------------------------------------------------------------
# B. OrchestratorResult
# ---------------------------------------------------------------------------

class TestOrchestratorResult:
    def test_is_ok_success(self):
        r = OrchestratorResult(success=True, iterations=1, final_quality=80)
        assert r.is_ok() is True

    def test_is_ok_failure(self):
        r = OrchestratorResult(success=False, error="timeout")
        assert r.is_ok() is False

    def test_defaults(self):
        r = OrchestratorResult(success=True)
        assert r.iterations == 0
        assert r.final_quality == 0
        assert r.reflections == []
        assert r.timed_out is False


# ---------------------------------------------------------------------------
# C. AgentOrchestrator.create
# ---------------------------------------------------------------------------

class TestOrchestratorCreate:
    def test_create_factory(self):
        bus = _bus()
        orch = AgentOrchestrator.create(bus=bus, max_iterations=5)
        assert orch._architect is not None
        assert orch._coder is not None
        assert orch._reviewer is not None
        assert orch._tester is not None
        assert orch._max_iter == 5


# ---------------------------------------------------------------------------
# D. Pipeline nominal
# ---------------------------------------------------------------------------

class TestPipelineNominal:
    def test_full_success(self):
        """Pipeline complet -> succes a la premiere iteration."""
        orch = _make_orchestrator()
        result = orch.run("Create a parser function")
        assert result.success is True
        assert result.iterations == 1
        assert result.final_quality == 85
        assert result.timed_out is False

    def test_architect_always_fails(self):
        """Architect echoue a chaque fois -> OrchestratorResult.success=False."""
        orch = _make_orchestrator(
            arch_results=[_fail_result(error="decomposition failed")],
            max_iterations=3,
        )
        result = orch.run("some intent")
        assert result.success is False
        assert result.iterations == 0  # quality_history vide = 0 iterations comptees
        assert result.error is not None


# ---------------------------------------------------------------------------
# E. KarpathyLoop
# ---------------------------------------------------------------------------

class TestKarpathyLoop:
    def test_reviewer_rejection_then_success(self):
        """
        1re iteration : Reviewer rejette.
        2e iteration  : Reviewer accepte, Tester succes.
        -> succes global a l'iteration 2.
        """
        orch = _make_orchestrator(
            reviewer_results=[
                _fail_result(
                    error="SyntaxError",
                    reflection="Reviewer: SyntaxError ligne 3",
                    reviewer_ok=False,
                    task_id="sub_001",
                ),
                _ok_result(task_id="sub_001", reviewer_ok=True, forwarded_to="tester"),
            ],
            max_iterations=5,
        )
        result = orch.run("build a module")
        assert result.success is True
        assert result.iterations == 2
        # La reflexion de la 1re iteration a ete accumulee
        assert len(result.reflections) >= 1
        assert "Reviewer" in result.reflections[0]

    def test_tester_rejection_then_success(self):
        """
        1re iteration : Tester rejette (quality_score=40).
        2e iteration  : Tester succes (quality_score=90).
        """
        orch = _make_orchestrator(
            tester_results=[
                _fail_result(
                    error="quality_score=40 < 70",
                    reflection="Tester: sandbox_passed=True, tests_failed=1",
                    quality_score=40,
                    tester_ok=False,
                    task_id="sub_001",
                ),
                _ok_result(
                    task_id="sub_001",
                    sandbox_passed=True,
                    quality_score=90,
                    tester_ok=True,
                ),
            ],
            max_iterations=5,
        )
        result = orch.run("optimize algo")
        assert result.success is True
        assert result.final_quality == 90

    def test_stagnation_stops_early(self):
        """
        Tester echoue 3 fois avec le meme score -> stagnation detectee (V8-Regle-18).
        Le pipeline doit s'arreter avant max_iterations=10.
        """
        stagnant_tester = _fail_result(
            error="quality_score=30 < 70",
            reflection="Tester: sandbox_passed=False",
            quality_score=30,
            tester_ok=False,
            task_id="sub_001",
        )
        orch = _make_orchestrator(
            tester_results=[stagnant_tester],  # meme resultat indefiniment
            max_iterations=10,
            max_stagnation=3,
        )
        result = orch.run("broken task")
        assert result.success is False
        # Doit s'arreter a 3 (max_stagnation), pas a 10 (max_iterations)
        assert result.iterations <= 4  # 3 stagnantes + marge


# ---------------------------------------------------------------------------
# F. Timeout + SkillLibrary
# ---------------------------------------------------------------------------

class TestTimeoutAndSkillLibrary:
    def test_timeout_zero_returns_timed_out(self):
        """timeout_sec=0 -> timed_out=True des la premiere iteration."""
        # On met un delai dans l'Architect pour que le timeout s'active
        bus = _bus()
        arch = MagicMock()
        arch.card = MagicMock()
        arch.card.name = "architect"

        def slow_architect(*args, **kwargs):
            time.sleep(0.01)
            return _ok_result(dispatched=["sub_001"], sub_contracts=1, specs_found=0)

        arch.run_task.side_effect = slow_architect

        orch = AgentOrchestrator(
            bus=bus,
            architect=arch,
            coder=MagicMock(),
            reviewer=MagicMock(),
            tester=MagicMock(),
            timeout_sec=0,
            max_iterations=5,
        )
        result = orch.run("slow intent")
        assert result.timed_out is True
        assert result.success is False

    def test_skill_library_injected_in_context(self):
        """
        Quand une SkillLibrary est injectee, retrieve() est appele et
        le resultat est passe dans le contexte du Coder.
        """
        skill_lib = MagicMock()
        skill_lib.retrieve.return_value = []  # pas de skills pour ce test
        skill_lib.format_for_prompt.return_value = ""

        orch = _make_orchestrator(skill_lib=skill_lib)
        result = orch.run("use skills please")
        # retrieve() doit avoir ete appele (au moins 1 fois)
        skill_lib.retrieve.assert_called()
        assert result.success is True
