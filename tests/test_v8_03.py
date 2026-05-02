# -*- coding: utf-8-sig -*-
"""
Tests V8-03 -- BaseAgent, ArchitectAgent, CoderAgent.

Regles :
- 0 dependance Ollama / SQLite reelle (bus en memoire :memory:).
- 14 tests couvrant : allowlist MCP, decomposition, dispatch bus,
  recovery policy, run_from_bus, stubs.
"""
from __future__ import annotations

import pytest

from core.agents.a2a_bus import A2ALocalBus, TaskContract
from core.agents.agent_card import (
    AgentCard,
    AgentRegistry,
    RecoveryPolicy,
    AGENT_MCP_ALLOWLIST,
    ARCHITECT_POLICY,
    CODER_POLICY,
)
from core.agents.base_agent import AgentResult, BaseAgent
from core.agents.architect_agent import ArchitectAgent, _detect_domain, _decompose_intent
from core.agents.coder_agent import CoderAgent, _build_patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    """Bus SQLite en memoire, isole par test."""
    b = A2ALocalBus(db_path=":memory:")
    yield b
    b.purge()


@pytest.fixture
def architect(bus):
    return ArchitectAgent.create(bus=bus)


@pytest.fixture
def coder(bus):
    return CoderAgent.create(bus=bus)


def _make_contract(intent="add login page", task_id="t_001"):
    return TaskContract(
        task_id=task_id,
        intent=intent,
        domain="ui",
        source_agent="nl_adapter",
        target_agent="architect",
    )


# ---------------------------------------------------------------------------
# 1. AgentResult
# ---------------------------------------------------------------------------

class TestAgentResult:
    def test_is_ok_true(self):
        r = AgentResult(success=True, payload={"x": 1})
        assert r.is_ok() is True

    def test_is_ok_false(self):
        r = AgentResult(success=False, error="oops")
        assert r.is_ok() is False

    def test_default_payload_is_dict(self):
        r = AgentResult(success=True)
        assert isinstance(r.payload, dict)


# ---------------------------------------------------------------------------
# 2. BaseAgent -- ABC & _call_mcp
# ---------------------------------------------------------------------------

class ConcreteAgent(BaseAgent):
    """Agent minimal pour tester BaseAgent."""
    def run_task(self, contract):
        return AgentResult(success=True)


class TestBaseAgentMCP:
    def _card(self, name="coder"):
        return AgentCard(
            name=name,
            version="8.0.0",
            capabilities=["code_generation", "ast_patching", "skill_injection"],
            mcp_tools=AGENT_MCP_ALLOWLIST[name],
            recovery_policy=CODER_POLICY,
        )

    def test_call_mcp_allowed_returns_empty_in_test_mode(self, bus):
        agent = ConcreteAgent(card=self._card("coder"), bus=bus, mcp_caller=None)
        result = agent._call_mcp("edit_batch", {"x": 1})
        assert result == {}

    def test_call_mcp_forbidden_raises(self, bus):
        agent = ConcreteAgent(card=self._card("coder"), bus=bus)
        with pytest.raises(PermissionError):
            agent._call_mcp("sandbox_run", {})   # non dans allowlist coder

    def test_call_mcp_with_real_caller(self, bus):
        calls = []
        def fake_caller(tool, params):
            calls.append((tool, params))
            return {"ok": True}

        agent = ConcreteAgent(card=self._card("coder"), bus=bus, mcp_caller=fake_caller)
        result = agent._call_mcp("edit_batch", {"x": 1})
        assert result == {"ok": True}
        assert calls == [("edit_batch", {"x": 1})]

    def test_send_receive_roundtrip(self, bus):
        card = AgentCard(
            name="architect",
            version="8.0.0",
            capabilities=["planning", "decomposition", "memory_search"],
            mcp_tools=AGENT_MCP_ALLOWLIST["architect"],
            recovery_policy=ARCHITECT_POLICY,
        )
        agent = ConcreteAgent(card=card, bus=bus)
        agent._send(to="coder", task_id="t_x", payload={"hello": "world"})
        msg = bus.receive("coder")
        assert msg is not None
        assert msg.payload == {"hello": "world"}


# ---------------------------------------------------------------------------
# 3. ArchitectAgent -- decomposition & dispatch
# ---------------------------------------------------------------------------

class TestDetectDomain:
    def test_ui(self):
        assert _detect_domain("add login page") == "ui"

    def test_api(self):
        assert _detect_domain("create REST api endpoint") == "api"

    def test_global_fallback(self):
        assert _detect_domain("do something weird") == "global"


class TestDecomposeIntent:
    def test_single_intent_produces_one_contract(self):
        contracts = _decompose_intent("add login page", "parent_01")
        assert len(contracts) == 1
        assert contracts[0].target_agent == "coder"
        assert contracts[0].source_agent == "architect"

    def test_and_split_produces_two_contracts(self):
        contracts = _decompose_intent("add login page and create api route", "parent_01")
        assert len(contracts) == 2

    def test_task_ids_are_unique(self):
        contracts = _decompose_intent("add form and add table", "parent_01")
        ids = [c.task_id for c in contracts]
        assert len(set(ids)) == len(ids)

    def test_parent_task_id_set(self):
        contracts = _decompose_intent("add login page", "parent_42")
        assert contracts[0].parent_task_id == "parent_42"


class TestArchitectAgentRunTask:
    def test_run_task_success_dispatches_to_bus(self, architect, bus):
        contract = _make_contract("add login page")
        result = architect.run_task(contract)

        assert result.success is True
        assert "dispatched" in result.payload
        assert len(result.payload["dispatched"]) == 1

        # Le message doit etre dans la queue coder
        msg = bus.receive("coder")
        assert msg is not None
        assert "contract" in msg.payload

    def test_run_task_and_splits_dispatch_two(self, architect, bus):
        contract = _make_contract("add page and create api")
        result = architect.run_task(contract)
        assert result.payload["sub_contracts"] == 2
        # 2 messages dans la queue coder
        assert bus.peek("coder") == 2

    def test_mcp_violation_propagates(self, bus):
        """architect ne peut pas appeler sandbox_run."""
        arch = ArchitectAgent.create(bus=bus)
        with pytest.raises(PermissionError):
            arch._call_mcp("sandbox_run", {})


# ---------------------------------------------------------------------------
# 4. CoderAgent -- patch & bus
# ---------------------------------------------------------------------------

class TestBuildPatch:
    def test_patch_contains_required_keys(self):
        contract = _make_contract("add login page", "t_abc")
        patch = _build_patch(contract, skills=[])
        for key in ("task_id", "intent", "domain", "skills", "edits"):
            assert key in patch

    def test_patch_reflects_contract(self):
        contract = _make_contract("build api endpoint", "t_xyz")
        contract.domain = "api"
        patch = _build_patch(contract, skills=["s1"])
        assert patch["intent"] == "build api endpoint"
        assert patch["skills"] == ["s1"]


class TestCoderAgentRunTask:
    def test_run_task_success(self, coder):
        contract = TaskContract(
            task_id="c_001",
            intent="add login form",
            domain="ui",
            source_agent="architect",
            target_agent="coder",
        )
        result = coder.run_task(contract)
        assert result.success is True
        assert "patch" in result.payload
        assert "edit_result" in result.payload

    def test_run_from_bus_consumes_message(self, bus, coder):
        """run_from_bus lit un contrat depuis le bus et execute run_task."""
        contract = TaskContract(
            task_id="c_bus_01",
            intent="fix import",
            domain="global",
            source_agent="architect",
            target_agent="coder",
        )
        bus.send(
            to="coder",
            from_="architect",
            task_id=contract.task_id,
            payload={"contract": contract.to_dict()},
        )
        result = coder.run_from_bus(timeout_sec=0)
        assert result is not None
        assert result.success is True
        # Le message doit etre consomme
        assert bus.peek("coder") == 0

    def test_run_from_bus_no_message_returns_none(self, coder):
        result = coder.run_from_bus(timeout_sec=0)
        assert result is None

    def test_mcp_violation_propagates(self, bus):
        cod = CoderAgent.create(bus=bus)
        with pytest.raises(PermissionError):
            cod._call_mcp("sandbox_run", {})   # non dans allowlist coder
