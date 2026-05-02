# -*- coding: utf-8-sig -*-
"""
tests/test_v9_07.py -- Sprint V9-07 : EducatorAgent dans KarpathyLoop

Verifie que AgentOrchestrator integre correctement l'EducatorAgent
en tant que satellite de curation post-pipeline.

Regles :
- educator=None toujours accepte (retrocompat tests V8-06)
- educator.run_task() appele UNE fois apres la boucle KarpathyLoop
- educator_skills repercute dans OrchestratorResult
- Exception dans educator -> swallow + log (jamais propager)
- Le thread daemon de run_task() ne bloque pas le retour de run()
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.agent_orchestrator import AgentOrchestrator, OrchestratorResult
from core.agents.base_agent import AgentResult


# ---------------------------------------------------------------------------
# Helpers de construction
# ---------------------------------------------------------------------------

def _make_bus() -> A2ALocalBus:
    return A2ALocalBus(db_path=":memory:")


def _make_stub_agent(success: bool = True, payload: dict | None = None):
    """Fabrique un agent stubbe qui retourne toujours le resultat donne."""
    agent = MagicMock()
    agent.run_task.return_value = AgentResult(
        success=success,
        payload=payload or {},
    )
    agent.card = MagicMock()
    agent.card.name = "stub"
    return agent


def _make_orchestrator(bus, educator=None, timeout_sec=60):
    """Cree un AgentOrchestrator minimal avec tous les agents stubbes."""
    # Architect retourne un sous-contrat dispatche
    architect = _make_stub_agent(
        success=True,
        payload={"dispatched": ["sub_001"]},
    )
    coder = _make_stub_agent(
        success=True,
        payload={"patch": {"intent": "test"}, "generated_code": "def f(): pass"},
    )
    reviewer = _make_stub_agent(success=True, payload={})
    tester = _make_stub_agent(
        success=True,
        payload={"quality_score": 85, "tester_ok": True},
    )
    return AgentOrchestrator(
        bus=bus,
        architect=architect,
        coder=coder,
        reviewer=reviewer,
        tester=tester,
        educator=educator,
        timeout_sec=timeout_sec,
    )


# ---------------------------------------------------------------------------
# TestOrchestratorResultEducatorSkills
# ---------------------------------------------------------------------------

class TestOrchestratorResultEducatorSkills:
    """OrchestratorResult -- champ educator_skills."""

    def test_educator_skills_default_zero(self):
        """educator_skills vaut 0 par defaut."""
        result = OrchestratorResult(success=True)
        assert result.educator_skills == 0

    def test_educator_skills_set(self):
        """educator_skills peut etre positionne."""
        result = OrchestratorResult(success=True, educator_skills=42)
        assert result.educator_skills == 42


# ---------------------------------------------------------------------------
# TestOrchestratorWithoutEducator
# ---------------------------------------------------------------------------

class TestOrchestratorWithoutEducator:
    """Sans educator injecte (retrocompat V8-06)."""

    def test_run_without_educator_succeeds(self):
        """educator=None -> pas d'erreur, pipeline fonctionne normalement."""
        bus = _make_bus()
        orch = _make_orchestrator(bus, educator=None)
        result = orch.run("creer une fonction foo()")
        assert result.success is True
        assert result.educator_skills == 0

    def test_create_without_educator(self):
        """AgentOrchestrator.create() accepte educator absent (retrocompat)."""
        bus = _make_bus()
        orch = AgentOrchestrator.create(bus=bus, educator=None, timeout_sec=60)
        assert orch._educator is None

    def test_create_with_educator_none_default(self):
        """educator non passe -> None par defaut."""
        bus = _make_bus()
        orch = AgentOrchestrator.create(bus=bus, timeout_sec=60)
        assert orch._educator is None


# ---------------------------------------------------------------------------
# TestOrchestratorWithEducator
# ---------------------------------------------------------------------------

class TestOrchestratorWithEducator:
    """Avec educator injecte."""

    def _make_educator_mock(self, skills_ingested: int = 5) -> MagicMock:
        educator = MagicMock()
        educator.run_task.return_value = AgentResult(
            success=True,
            payload={"skills_ingested": skills_ingested, "status": "started"},
        )
        return educator

    def test_educator_called_after_pipeline(self):
        """educator.run_task() est appele apres la boucle KarpathyLoop."""
        bus = _make_bus()
        educator = self._make_educator_mock(skills_ingested=7)
        orch = _make_orchestrator(bus, educator=educator)
        result = orch.run("creer une fonction bar()")
        educator.run_task.assert_called_once()
        assert result.educator_skills == 7

    def test_educator_contract_has_correct_target(self):
        """Le contrat envoye a educator a target_agent='educator'."""
        bus = _make_bus()
        educator = self._make_educator_mock()
        orch = _make_orchestrator(bus, educator=educator)
        orch.run("test intent")
        call_args = educator.run_task.call_args[0][0]  # premier arg positionnel
        assert call_args.target_agent == "educator"
        assert call_args.source_agent == "orchestrator"

    def test_educator_contract_dry_run_false(self):
        """Le contrat educator a dry_run=False (curation reelle)."""
        bus = _make_bus()
        educator = self._make_educator_mock()
        orch = _make_orchestrator(bus, educator=educator)
        orch.run("test intent")
        call_args = educator.run_task.call_args[0][0]
        assert call_args.context.get("dry_run") is False

    def test_educator_exception_swallowed(self):
        """Exception dans educator.run_task() -> swallow, pipeline retourne quand meme."""
        bus = _make_bus()
        educator = MagicMock()
        educator.run_task.side_effect = RuntimeError("reseau indisponible")
        orch = _make_orchestrator(bus, educator=educator)
        result = orch.run("test intent")
        # pipeline ne doit pas etre affecte
        assert result.success is True
        assert result.educator_skills == 0

    def test_educator_failure_skills_zero(self):
        """educator.run_task() echoue (success=False) -> educator_skills reste 0."""
        bus = _make_bus()
        educator = MagicMock()
        educator.run_task.return_value = AgentResult(
            success=False,
            payload={"skills_ingested": 3},
            error="Erreur reseau",
        )
        orch = _make_orchestrator(bus, educator=educator)
        result = orch.run("test intent")
        assert result.educator_skills == 0

    def test_educator_called_even_on_pipeline_failure(self):
        """educator est appele meme si le pipeline Karpathy echoue."""
        bus = _make_bus()
        educator = self._make_educator_mock(skills_ingested=2)
        # Tester toujours en echec
        architect = _make_stub_agent(
            success=True, payload={"dispatched": ["sub_001"]}
        )
        coder = _make_stub_agent(
            success=True,
            payload={"patch": {"intent": "x"}, "generated_code": "def f(): pass"},
        )
        reviewer = _make_stub_agent(success=True, payload={})
        tester = _make_stub_agent(
            success=False,
            payload={"quality_score": 10, "reflection": "Tester: echec sandbox"},
        )
        orch = AgentOrchestrator(
            bus=bus,
            architect=architect,
            coder=coder,
            reviewer=reviewer,
            tester=tester,
            educator=educator,
            max_iterations=1,
            timeout_sec=60,
        )
        result = orch.run("test echec pipeline")
        educator.run_task.assert_called_once()
        assert result.educator_skills == 2
