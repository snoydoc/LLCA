# -*- coding: utf-8-sig -*-
"""
tests/test_refacto_04.py -- Sprint REFACTO-04 : KarpathyLoop extraite

Verifie que :
- KarpathyLoop fonctionne independamment d'AgentOrchestrator
- AgentOrchestrator delegue correctement a self._loop
- LoopResult contient les champs attendus
- _detect_stagnation module-level reste accessible depuis agent_orchestrator
- Retrocompat totale des tests V8-06 (agent_orchestrator.py inchange en API)
"""
from __future__ import annotations

import time
import pytest
from unittest.mock import MagicMock

from core.agents.orchestrator_loop import (
    KarpathyLoop,
    LoopResult,
    _detect_stagnation,
)
from core.agents.agent_orchestrator import (
    AgentOrchestrator,
    OrchestratorResult,
    _detect_stagnation as _detect_stagnation_orch,  # re-export retrocompat
)
from core.agents.a2a_bus import A2ALocalBus
from core.agents.base_agent import AgentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub(success: bool = True, payload: dict | None = None) -> MagicMock:
    agent = MagicMock()
    agent.run_task.return_value = AgentResult(
        success=success, payload=payload or {}
    )
    return agent


def _make_loop(
    success_tester: bool = True,
    quality: int = 80,
    max_iter: int = 5,
    max_stagnation: int = 3,
    timeout_sec: int = 60,
) -> KarpathyLoop:
    architect = _stub(True, {"dispatched": ["sub_001"]})
    coder = _stub(True, {"generated_code": "def f(): pass", "patch": {"intent": "x"}})
    reviewer = _stub(True, {})
    tester = _stub(success_tester, {"quality_score": quality, "tester_ok": success_tester})
    return KarpathyLoop(
        architect=architect,
        coder=coder,
        reviewer=reviewer,
        tester=tester,
        max_iterations=max_iter,
        max_stagnation=max_stagnation,
        timeout_sec=timeout_sec,
    )


def _make_orchestrator(timeout_sec: int = 60) -> AgentOrchestrator:
    bus = A2ALocalBus(db_path=":memory:")
    architect = _stub(True, {"dispatched": ["sub_001"]})
    coder = _stub(True, {"generated_code": "def f(): pass", "patch": {"intent": "x"}})
    reviewer = _stub(True, {})
    tester = _stub(True, {"quality_score": 85, "tester_ok": True})
    return AgentOrchestrator(
        bus=bus,
        architect=architect,
        coder=coder,
        reviewer=reviewer,
        tester=tester,
        timeout_sec=timeout_sec,
    )


# ---------------------------------------------------------------------------
# TestLoopResult
# ---------------------------------------------------------------------------

class TestLoopResult:
    """LoopResult dataclass."""

    def test_default_values(self):
        r = LoopResult(success=True)
        assert r.iterations == 0
        assert r.final_quality == 0
        assert r.last_error is None
        assert r.reflections == []
        assert r.timed_out is False

    def test_set_fields(self):
        r = LoopResult(
            success=False,
            iterations=3,
            final_quality=40,
            last_error="echec sandbox",
            reflections=["r1"],
            timed_out=True,
        )
        assert r.success is False
        assert r.iterations == 3
        assert r.final_quality == 40
        assert r.last_error == "echec sandbox"
        assert r.timed_out is True


# ---------------------------------------------------------------------------
# TestDetectStagnation
# ---------------------------------------------------------------------------

class TestDetectStagnation:
    """_detect_stagnation module-level (orchestrator_loop) et re-export (agent_orchestrator)."""

    def test_stagnation_detected(self):
        assert _detect_stagnation([5, 5, 5], 3) is True

    def test_no_stagnation_varying(self):
        assert _detect_stagnation([5, 6, 5], 3) is False

    def test_history_too_short(self):
        assert _detect_stagnation([5, 5], 3) is False

    def test_reexport_from_orchestrator(self):
        """_detect_stagnation re-exporte depuis agent_orchestrator."""
        assert _detect_stagnation_orch([7, 7, 7], 3) is True
        assert _detect_stagnation_orch([7, 8, 7], 3) is False


# ---------------------------------------------------------------------------
# TestKarpathyLoopDirect
# ---------------------------------------------------------------------------

class TestKarpathyLoopDirect:
    """Tests directs de KarpathyLoop sans AgentOrchestrator."""

    def test_success_first_iteration(self):
        loop = _make_loop(success_tester=True, quality=90)
        deadline = time.monotonic() + 60
        result = loop.run("task_001", "creer foo()", deadline)
        assert result.success is True
        assert result.iterations == 1
        assert result.final_quality == 90
        assert result.timed_out is False

    def test_failure_all_iterations(self):
        loop = _make_loop(success_tester=False, quality=10, max_iter=2, max_stagnation=5)
        deadline = time.monotonic() + 60
        result = loop.run("task_002", "intent echec", deadline)
        assert result.success is False
        assert result.iterations == 2

    def test_stagnation_stops_early(self):
        """3 iterations identiques -> stagnation -> arret avant max_iter."""
        loop = _make_loop(success_tester=False, quality=20, max_iter=10, max_stagnation=3)
        deadline = time.monotonic() + 60
        result = loop.run("task_003", "stagnation", deadline)
        assert result.success is False
        assert result.iterations == 3  # arrete a max_stagnation

    def test_timeout_immediate(self):
        """deadline dans le passe -> timeout a la premiere iteration."""
        loop = _make_loop(max_iter=5)
        deadline = time.monotonic() - 1  # dans le passe
        result = loop.run("task_004", "intent timeout", deadline)
        assert result.timed_out is True
        assert result.success is False

    def test_reflections_accumulated(self):
        """Les reflexions Reviewer/Tester sont accumulees dans LoopResult."""
        architect = _stub(True, {"dispatched": ["sub_x"]})
        coder = _stub(True, {"generated_code": "def f(): pass", "patch": {"intent": "x"}})
        reviewer = _stub(
            False,
            {"reflection": "syntax error", "quality_score": 0},
        )
        tester = _stub(False, {"quality_score": 0, "reflection": "test echec"})
        loop = KarpathyLoop(
            architect=architect,
            coder=coder,
            reviewer=reviewer,
            tester=tester,
            max_iterations=2,
            max_stagnation=5,
            timeout_sec=60,
        )
        deadline = time.monotonic() + 60
        result = loop.run("task_005", "intent", deadline)
        assert len(result.reflections) > 0
        assert any("Reviewer" in r for r in result.reflections)

    def test_skill_library_injected(self):
        """Si skill_library fourni, retrieve() est appele."""
        loop = _make_loop()
        skill_lib = MagicMock()
        skill_lib.retrieve.return_value = []
        loop._skill_lib = skill_lib
        deadline = time.monotonic() + 60
        loop.run("task_006", "intent avec skills", deadline)
        skill_lib.retrieve.assert_called()

    def test_skill_library_none_no_error(self):
        """skill_library=None -> aucune erreur."""
        loop = _make_loop()
        loop._skill_lib = None
        deadline = time.monotonic() + 60
        result = loop.run("task_007", "intent sans skills", deadline)
        assert result.success is True


# ---------------------------------------------------------------------------
# TestOrchestratorDelegatesLoop
# ---------------------------------------------------------------------------

class TestOrchestratorDelegatesLoop:
    """Verifie que AgentOrchestrator delegue a self._loop."""

    def test_orchestrator_has_loop(self):
        orch = _make_orchestrator()
        assert hasattr(orch, "_loop")
        assert isinstance(orch._loop, KarpathyLoop)

    def test_run_delegates_to_loop(self):
        """AgentOrchestrator.run() appelle self._loop.run()."""
        orch = _make_orchestrator()
        mock_loop = MagicMock()
        mock_loop.run.return_value = LoopResult(
            success=True,
            iterations=1,
            final_quality=80,
            timed_out=False,
        )
        orch._loop = mock_loop
        result = orch.run("test intent")
        mock_loop.run.assert_called_once()
        assert result.success is True
        assert result.final_quality == 80

    def test_timeout_zero_not_delegated(self):
        """timeout_sec=0 -> retour immediat AVANT delegation a la loop."""
        orch = _make_orchestrator(timeout_sec=0)
        mock_loop = MagicMock()
        orch._loop = mock_loop
        result = orch.run("intent timeout")
        mock_loop.run.assert_not_called()
        assert result.timed_out is True

    def test_loop_timeout_propagated(self):
        """Si loop retourne timed_out=True -> OrchestratorResult.timed_out=True."""
        orch = _make_orchestrator()
        mock_loop = MagicMock()
        mock_loop.run.return_value = LoopResult(
            success=False,
            iterations=2,
            final_quality=0,
            last_error="Pipeline timeout",
            timed_out=True,
        )
        orch._loop = mock_loop
        result = orch.run("intent loop timeout")
        assert result.timed_out is True
        assert result.success is False

    def test_loop_failure_propagated(self):
        """Si loop retourne success=False -> OrchestratorResult.success=False."""
        orch = _make_orchestrator()
        mock_loop = MagicMock()
        mock_loop.run.return_value = LoopResult(
            success=False,
            iterations=3,
            final_quality=20,
            last_error="qualite insuffisante",
            timed_out=False,
        )
        orch._loop = mock_loop
        result = orch.run("intent echec")
        assert result.success is False
        assert result.error == "qualite insuffisante"
        assert result.iterations == 3
