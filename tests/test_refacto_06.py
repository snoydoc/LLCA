# -*- coding: utf-8-sig -*-
"""
Tests REFACTO-06 -- ArchitectDecomposer : detection domaine + decomposition heuristique + LLM.

18 tests couvrant :
  TestDetectDomain (4)          : ui, api, database, fallback global
  TestDecomposeIntent (4)       : 1 contrat, split "and", split "et", domaine detecte
  TestParseLlmDecomposition (3) : JSON valide, malformed, plafond 3
  TestArchitectDecomposer (4)   : llm=None->heuristique, llm mock->llm,
                                  llm echec->heuristique, decomposed_by correct
  TestArchitectDelegates (3)    : decomposer instancie, decompose() appele dans run_task,
                                  _decompose_with_llm retrocompat wrapper
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from core.agents.architect_decomposer import (
    ArchitectDecomposer,
    _detect_domain,
    _decompose_intent,
    _parse_llm_decomposition,
)
from core.agents.a2a_bus import A2ALocalBus, TaskContract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_contract(intent: str = "add a parse_json function", task_id: str = "t_r06") -> TaskContract:
    return TaskContract(
        task_id=task_id,
        intent=intent,
        domain="global",
        source_agent="orchestrator",
        target_agent="architect",
    )


def _mock_llm(response: str):
    llm = MagicMock()
    llm.ollama = MagicMock()
    llm.ollama.model = "qwen2.5-coder:3b"
    llm.generate_text = MagicMock(return_value=response)
    return llm


def _valid_json(*intents_domains) -> str:
    return json.dumps([{"intent": i, "domain": d} for i, d in intents_domains])


@pytest.fixture
def bus():
    b = A2ALocalBus(db_path=":memory:")
    yield b
    b.purge()


# ---------------------------------------------------------------------------
# TestDetectDomain
# ---------------------------------------------------------------------------

class TestDetectDomain:

    def test_detects_ui(self):
        assert _detect_domain("add a login page component") == "ui"

    def test_detects_api(self):
        assert _detect_domain("create REST endpoint for users") == "api"

    def test_detects_database(self):
        assert _detect_domain("write a database migration script") == "database"

    def test_falls_back_to_global(self):
        assert _detect_domain("refactor the thing") == "global"


# ---------------------------------------------------------------------------
# TestDecomposeIntent
# ---------------------------------------------------------------------------

class TestDecomposeIntent:

    def test_single_intent_returns_one_contract(self):
        contracts = _decompose_intent("add parse_json", "parent_001")
        assert len(contracts) == 1
        assert contracts[0].intent == "add parse_json"
        assert contracts[0].source_agent == "architect"
        assert contracts[0].target_agent == "coder"

    def test_split_on_and(self):
        contracts = _decompose_intent("add login and add logout", "parent_002")
        assert len(contracts) == 2
        assert "login" in contracts[0].intent
        assert "logout" in contracts[1].intent

    def test_split_on_et(self):
        contracts = _decompose_intent("ajouter login et ajouter logout", "parent_003")
        assert len(contracts) == 2

    def test_domain_detected_per_part(self):
        contracts = _decompose_intent("add api endpoint and create ui form", "parent_004")
        domains = {c.domain for c in contracts}
        assert "api" in domains
        assert "ui" in domains


# ---------------------------------------------------------------------------
# TestParseLlmDecomposition
# ---------------------------------------------------------------------------

class TestParseLlmDecomposition:

    def test_valid_json_returns_contracts(self):
        raw = _valid_json(("add auth", "api"), ("add tests", "test"))
        contracts = _parse_llm_decomposition(raw, "parent_005")
        assert len(contracts) == 2
        assert contracts[0].intent == "add auth"
        assert contracts[1].domain == "test"

    def test_invalid_json_returns_empty(self):
        contracts = _parse_llm_decomposition("not json", "parent_006")
        assert contracts == []

    def test_plafond_3_enforced(self):
        raw = _valid_json(
            ("t1", "global"), ("t2", "ui"), ("t3", "api"), ("t4", "test")
        )
        contracts = _parse_llm_decomposition(raw, "parent_007")
        assert len(contracts) == 3


# ---------------------------------------------------------------------------
# TestArchitectDecomposer
# ---------------------------------------------------------------------------

class TestArchitectDecomposer:

    def test_llm_none_returns_heuristic(self):
        """llm=None -> heuristique, decomposed_by='heuristic'."""
        decomposer = ArchitectDecomposer()
        contracts, by = decomposer.decompose(_make_contract("add feature"), llm=None)
        assert len(contracts) >= 1
        assert by == "heuristic"
        assert contracts[0].source_agent == "architect"

    def test_llm_valid_returns_llm(self):
        """LLM retourne JSON valide -> decomposed_by='llm'."""
        decomposer = ArchitectDecomposer()
        llm = _mock_llm(_valid_json(("add auth module", "api"), ("add user model", "database")))
        contracts, by = decomposer.decompose(_make_contract("add auth"), llm=llm)
        assert by == "llm"
        assert len(contracts) == 2
        assert contracts[0].intent == "add auth module"

    def test_llm_failure_falls_back_to_heuristic(self):
        """LLM leve une exception -> fallback heuristique, pas d'exception propagee."""
        decomposer = ArchitectDecomposer()
        llm = _mock_llm("")
        llm.generate_text.side_effect = ConnectionError("Ollama down")
        contracts, by = decomposer.decompose(_make_contract("add feature"), llm=llm)
        assert by == "heuristic"
        assert len(contracts) >= 1

    def test_llm_bad_json_falls_back_to_heuristic(self):
        """LLM retourne JSON invalide -> fallback heuristique."""
        decomposer = ArchitectDecomposer()
        llm = _mock_llm("Sure! Here are the sub-tasks: ...")
        contracts, by = decomposer.decompose(_make_contract("add feature"), llm=llm)
        assert by == "heuristic"
        assert len(contracts) >= 1


# ---------------------------------------------------------------------------
# TestArchitectDelegates
# ---------------------------------------------------------------------------

class TestArchitectDelegates:

    def _make_agent(self, bus, llm=None):
        from core.agents.architect_agent import ArchitectAgent
        return ArchitectAgent.create(bus=bus, llm_generator=llm)

    def test_decomposer_instanciated(self, bus):
        """self._decomposer est un ArchitectDecomposer apres __init__."""
        agent = self._make_agent(bus)
        assert isinstance(agent._decomposer, ArchitectDecomposer)

    def test_run_task_delegates_to_decomposer(self, bus):
        """run_task() appelle self._decomposer.decompose() exactement une fois."""
        agent = self._make_agent(bus)

        calls = []
        original = agent._decomposer.decompose

        def spy(contract, llm=None):
            calls.append((contract, llm))
            return original(contract, llm)

        agent._decomposer.decompose = spy
        result = agent.run_task(_make_contract())
        assert len(calls) == 1
        assert result.success is True

    def test_decompose_with_llm_retrocompat(self, bus):
        """_decompose_with_llm() sur l'agent reste accessible (retrocompat V8-09)."""
        agent = self._make_agent(bus)
        # Doit retourner une liste (vide ou non) sans lever
        result = agent._decompose_with_llm(_make_contract())
        assert isinstance(result, list)
