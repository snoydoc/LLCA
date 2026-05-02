# -*- coding: utf-8-sig -*-
"""
Tests V8-09 -- Integration LLMGenerator dans ArchitectAgent.

Regles :
- 0 dependance Ollama reelle : LLMGenerator mocke via injection.
- 0 dependance SQLite reelle : bus en memoire (:memory:).
- 11 tests couvrant :
    - _parse_llm_decomposition (JSON valide, malformed, fences, plafond 3, domaine invalide)
    - ArchitectAgent._decompose_with_llm (llm=None, llm ok, llm vide, llm exception, JSON invalide)
    - ArchitectAgent.run_task (sans llm -> heuristique, avec llm -> LLM, fallback heuristique)
    - ArchitectAgent.create (factory sans Ollama)
    - payload "decomposed_by" present dans AgentResult
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.architect_agent import (
    ArchitectAgent,
    _parse_llm_decomposition,
    _decompose_intent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    b = A2ALocalBus(db_path=":memory:")
    yield b
    b.purge()


def _make_contract(intent="add a parse_json function", task_id="t_v809"):
    return TaskContract(
        task_id=task_id,
        intent=intent,
        domain="global",
        source_agent="orchestrator",
        target_agent="architect",
    )


def _mock_llm(response: str):
    """Retourne un LLMGenerator mocke dont generate_text retourne response."""
    llm = MagicMock()
    llm.ollama = MagicMock()
    llm.ollama.model = "qwen2.5-coder:14b"
    llm.generate_text = MagicMock(return_value=response)
    return llm


def _valid_llm_response(*intents_domains):
    """Construit une reponse JSON LLM valide pour les intents/domaines donnes."""
    items = [{"intent": i, "domain": d} for i, d in intents_domains]
    return json.dumps(items)


# ---------------------------------------------------------------------------
# 1. _parse_llm_decomposition
# ---------------------------------------------------------------------------

class TestParseLlmDecomposition:
    def test_valid_single_item(self):
        raw = _valid_llm_response(("add parse_json", "global"))
        contracts = _parse_llm_decomposition(raw, "parent_001")
        assert len(contracts) == 1
        assert contracts[0].intent == "add parse_json"
        assert contracts[0].domain == "global"
        assert contracts[0].source_agent == "architect"
        assert contracts[0].target_agent == "coder"

    def test_valid_multiple_items(self):
        raw = _valid_llm_response(
            ("create auth module", "api"),
            ("add user model", "database"),
        )
        contracts = _parse_llm_decomposition(raw, "parent_002")
        assert len(contracts) == 2
        assert contracts[0].domain == "api"
        assert contracts[1].domain == "database"

    def test_plafond_3_items(self):
        raw = _valid_llm_response(
            ("task 1", "global"),
            ("task 2", "ui"),
            ("task 3", "api"),
            ("task 4", "test"),  # doit etre ignore
        )
        contracts = _parse_llm_decomposition(raw, "parent_003")
        assert len(contracts) == 3

    def test_markdown_fences_cleaned(self):
        raw = "```json\n" + _valid_llm_response(("add foo", "global")) + "\n```"
        contracts = _parse_llm_decomposition(raw, "parent_004")
        assert len(contracts) == 1
        assert contracts[0].intent == "add foo"

    def test_invalid_json_returns_empty(self):
        contracts = _parse_llm_decomposition("not json at all", "parent_005")
        assert contracts == []

    def test_empty_string_returns_empty(self):
        contracts = _parse_llm_decomposition("", "parent_006")
        assert contracts == []

    def test_invalid_domain_falls_back_to_global(self):
        raw = json.dumps([{"intent": "do something", "domain": "zork"}])
        contracts = _parse_llm_decomposition(raw, "parent_007")
        assert len(contracts) == 1
        assert contracts[0].domain == "global"

    def test_items_without_intent_skipped(self):
        raw = json.dumps([{"domain": "api"}, {"intent": "add foo", "domain": "api"}])
        contracts = _parse_llm_decomposition(raw, "parent_008")
        assert len(contracts) == 1
        assert contracts[0].intent == "add foo"

    def test_context_decomposed_by_llm(self):
        raw = _valid_llm_response(("add bar", "ui"))
        contracts = _parse_llm_decomposition(raw, "parent_009")
        assert contracts[0].context.get("decomposed_by") == "llm"

    def test_unique_task_ids_per_parent(self):
        raw = _valid_llm_response(("task A", "global"), ("task B", "global"))
        c1 = _parse_llm_decomposition(raw, "parent_AAA")
        c2 = _parse_llm_decomposition(raw, "parent_BBB")
        ids1 = {c.task_id for c in c1}
        ids2 = {c.task_id for c in c2}
        assert ids1.isdisjoint(ids2), "task_ids doivent dependre du parent_task_id"


# ---------------------------------------------------------------------------
# 2. ArchitectAgent._decompose_with_llm
# ---------------------------------------------------------------------------

class TestDecomposeWithLlm:
    def test_llm_none_returns_empty(self, bus):
        from core.agents.agent_card import AgentCard, ARCHITECT_POLICY, AGENT_MCP_ALLOWLIST
        card = AgentCard(
            name="architect",
            version="8.1.0",
            capabilities=["planning", "decomposition", "memory_search", "llm_generation"],
            mcp_tools=AGENT_MCP_ALLOWLIST["architect"],
            recovery_policy=ARCHITECT_POLICY,
        )
        agent = ArchitectAgent(card=card, bus=bus, llm_generator=None)
        result = agent._decompose_with_llm(_make_contract())
        assert result == []

    def test_llm_valid_response_returns_contracts(self, bus):
        llm = _mock_llm(_valid_llm_response(("add parse_json", "global"), ("add tests", "test")))
        agent = ArchitectAgent.create(bus=bus, llm_generator=llm)
        contracts = agent._decompose_with_llm(_make_contract("add parse_json and tests"))
        assert len(contracts) == 2
        assert contracts[0].intent == "add parse_json"
        assert contracts[1].intent == "add tests"

    def test_llm_empty_response_returns_empty(self, bus):
        agent = ArchitectAgent.create(bus=bus, llm_generator=_mock_llm(""))
        result = agent._decompose_with_llm(_make_contract())
        assert result == []

    def test_llm_exception_returns_empty(self, bus):
        llm = _mock_llm("")
        llm.generate_text.side_effect = ConnectionError("Ollama down")
        agent = ArchitectAgent.create(bus=bus, llm_generator=llm)
        result = agent._decompose_with_llm(_make_contract())
        assert result == []

    def test_llm_invalid_json_returns_empty(self, bus):
        agent = ArchitectAgent.create(bus=bus, llm_generator=_mock_llm("Sure! Here are the tasks:"))
        result = agent._decompose_with_llm(_make_contract())
        assert result == []


# ---------------------------------------------------------------------------
# 3. ArchitectAgent.run_task
# ---------------------------------------------------------------------------

class TestArchitectRunTaskV809:
    def test_run_task_without_llm_uses_heuristic(self, bus):
        """Sans LLM, decomposed_by doit etre 'heuristic'."""
        from core.agents.agent_card import AgentCard, ARCHITECT_POLICY, AGENT_MCP_ALLOWLIST
        card = AgentCard(
            name="architect",
            version="8.1.0",
            capabilities=["planning", "decomposition", "memory_search", "llm_generation"],
            mcp_tools=AGENT_MCP_ALLOWLIST["architect"],
            recovery_policy=ARCHITECT_POLICY,
        )
        agent = ArchitectAgent(card=card, bus=bus, llm_generator=None)
        result = agent.run_task(_make_contract("add login"))
        assert result.success is True
        assert result.payload["decomposed_by"] == "heuristic"
        assert result.payload["sub_contracts"] >= 1

    def test_run_task_with_llm_uses_llm(self, bus):
        """Avec LLM valide, decomposed_by doit etre 'llm'."""
        llm = _mock_llm(_valid_llm_response(("add login view", "ui"), ("add auth logic", "api")))
        agent = ArchitectAgent.create(bus=bus, llm_generator=llm)
        result = agent.run_task(_make_contract("add login"))
        assert result.success is True
        assert result.payload["decomposed_by"] == "llm"
        assert result.payload["sub_contracts"] == 2

    def test_run_task_llm_failure_falls_back_to_heuristic(self, bus):
        """LLM retourne JSON invalide -> fallback heuristique -> succes."""
        agent = ArchitectAgent.create(bus=bus, llm_generator=_mock_llm("oops not json"))
        result = agent.run_task(_make_contract("add feature"))
        assert result.success is True
        assert result.payload["decomposed_by"] == "heuristic"
        assert result.payload["sub_contracts"] >= 1

    def test_run_task_payload_has_required_keys(self, bus):
        agent = ArchitectAgent.create(bus=bus, llm_generator=None)
        result = agent.run_task(_make_contract())
        for key in ("dispatched", "sub_contracts", "specs_found", "decomposed_by"):
            assert key in result.payload, f"cle manquante : {key}"

    def test_run_task_dispatched_ids_non_empty(self, bus):
        agent = ArchitectAgent.create(bus=bus, llm_generator=None)
        result = agent.run_task(_make_contract("add parser"))
        assert len(result.payload["dispatched"]) >= 1

    def test_run_task_mcp_violation_propagates(self, bus):
        agent = ArchitectAgent.create(bus=bus, llm_generator=None)
        with pytest.raises(PermissionError):
            agent._call_mcp("edit_batch", {})

    def test_create_factory_without_ollama(self, bus):
        """Factory avec llm_generator=None ne doit pas lever d'exception."""
        agent = ArchitectAgent.create(bus=bus, llm_generator=None)
        assert agent is not None
        assert agent._llm is None or hasattr(agent._llm, "generate_text")
        result = agent.run_task(_make_contract())
        assert result.success is True
